# matcher_service/matcher.py
import os
import pika
import json
import time
import requests
import psycopg2

# --- Database Connection ---
def get_db_connection():
    conn = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST"),
        database=os.environ.get("POSTGRES_DB"),
        user=os.environ.get("POSTGRES_USER"),
        password=os.environ.get("POSTGRES_PASSWORD")
    )
    return conn

# --- Callback for RabbitMQ ---
def on_ride_request(ch, method, properties, body):
    data = json.loads(body)
    print(f" [x] Received ride request: {data}")

    rider_id = data['rider_id']
    latitude = data['latitude']
    longitude = data['longitude']
    trip_id = data['trip_id']

    # 1. Find nearest driver via Location Service
    location_service_url = os.environ.get("LOCATION_SERVICE_URL")
    driver_id = None
    last_location_error = None
    for attempt in range(1, 6):
        try:
            response = requests.get(
                f"{location_service_url}/find-nearest-driver",
                params={"latitude": latitude, "longitude": longitude},
                timeout=5,
            )
            response.raise_for_status()
            driver_info = response.json()
            if driver_info and 'driver_id' in driver_info:
                driver_id = driver_info['driver_id']
                print(f"[*] Found nearest driver: {driver_id}")
            last_location_error = None
            break
        except requests.exceptions.RequestException as e:
            last_location_error = e
            print(f" [!] Location service attempt {attempt}/5 failed: {e}")
            time.sleep(min(attempt, 5))
    if last_location_error is not None:
        print(" [!] Location service unavailable; discarding this request after retries")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    # 2. If driver found, update the trip in PostgreSQL
    if driver_id:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            # We need the real user ID of the driver from the users table
            cur.execute("SELECT id FROM users WHERE name = %s AND user_type = 'driver';", (driver_id,))
            driver_row = cur.fetchone()
            if driver_row is None:
                raise ValueError(f"Driver {driver_id!r} has no matching database user")
            driver_user_id = driver_row[0]

            cur.execute(
                "UPDATE trips SET driver_id = %s, status = 'assigned' WHERE id = %s;",
                (driver_user_id, trip_id)
            )
            conn.commit()
            cur.close()
            conn.close()
            print(f"[*] Successfully assigned driver {driver_id} (ID: {driver_user_id}) to trip {trip_id}")
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as e:
            print(f" [!] Database error: {e}")
            try:
                conn.rollback()
                cur.close()
                conn.close()
            except Exception:
                pass
            # Avoid a tight infinite retry loop on persistent database errors.
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    else:
        print(f" [!] No driver found for trip {trip_id}. Marking as cancelled.")
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE trips SET status = 'cancelled' WHERE id = %s;", (trip_id,))
            conn.commit()
            cur.close()
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as e:
            conn.rollback()
            print(f" [!] Could not update trip status: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        finally:
            conn.close()

# --- Main Loop ---
def main():
    rabbitmq_host = os.environ.get("RABBITMQ_HOST")
    rabbitmq_user = os.environ.get("RABBITMQ_USER", "georide")
    rabbitmq_password = os.environ.get("RABBITMQ_PASSWORD")
    while True:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(
                host=rabbitmq_host,
                credentials=pika.PlainCredentials(rabbitmq_user, rabbitmq_password),
                connection_attempts=3,
                retry_delay=2,
            ))
            break
        except pika.exceptions.AMQPConnectionError as e:
            print(f" [!] RabbitMQ is not ready: {e}. Retrying in 5 seconds.")
            time.sleep(5)
    channel = connection.channel()
    channel.queue_declare(queue='ride_requests', durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue='ride_requests', on_message_callback=on_ride_request)
    print(' [*] Waiting for ride requests. To exit press CTRL+C')
    channel.start_consuming()

if __name__ == '__main__':
    main()