import threading
import time
import schedule
from datetime import datetime
from app import User

class DatabaseKeepalive:
    """
    Database keepalive service that prevents cold starts by performing
    lightweight database operations at regular intervals.

    Think of this as your yoga studio's automatic lighting system -
    it keeps the lights on so students never walk into a dark room.
    """

    def __init__(self, interval_minutes=50):
        """
        Initialize keepalive service

        Args:
            interval_minutes (int): How often to ping the database (default: 50 minutes)
                                  Set to 50 minutes to ensure we ping before the 60-minute
                                  auto-pause delay kicks in
        """
        self.interval_minutes = interval_minutes
        self.is_running = False
        self.thread = None

    def ping_database(self):
        """
        Perform a lightweight database operation to keep it warm.
        """
        try:
            start_time = time.time()

            # Perform a simple, lightweight query
            # Count total users (doesn't return sensitive data)
            user_count = User.get_user_count()  # You'll need to add this method

            duration = time.time() - start_time

            print(f"Database keepalive ping successful at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Query duration: {duration:.2f}s")
            print(f"Total users in system: {user_count}")

            # Log if the database was cold (took longer than expected)
            if duration > 10:
                print(f"Database was cold (took {duration:.1f}s to respond)")
            else:
                print(f"Database was warm")

            return True

        except Exception as e:
            print(f"Database keepalive ping failed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Error: {str(e)}")
            return False

    def run_scheduler(self):
        """
        Run the scheduled keepalive pings in a separate thread.
        """
        print(f"Database keepalive service started (pinging every {self.interval_minutes} minutes)")

        while self.is_running:
            schedule.run_pending()
            time.sleep(60)  # Check every minute if it's time to run

    def start(self):
        """
        Start the keepalive service.
        """
        if self.is_running:
            print("Keepalive service is already running")
            return

        # Schedule the ping to run every interval
        schedule.every(self.interval_minutes).minutes.do(self.ping_database)

        # Also do an initial ping to warm up the database immediately
        print("Performing initial database warmup")
        self.ping_database()

        # Start the background scheduler thread
        self.is_running = True
        self.thread = threading.Thread(target=self.run_scheduler, daemon=True)
        self.thread.start()

        print(f"Database keepalive service is now running")

    def stop(self):
        """
        Stop the keepalive service.
        """
        if not self.is_running:
            print("Keepalive service is not running")
            return

        self.is_running = False
        schedule.clear()  # Clear all scheduled jobs

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)  # Wait up to 5 seconds for thread to finish

        print("Database keepalive service stopped")

# Global instance
db_keepalive = DatabaseKeepalive(interval_minutes=8)

def start_database_keepalive():
    """
    Start the database keepalive service.
    Call this when your Flask app starts up.
    """
    db_keepalive.start()

def stop_database_keepalive():
    """
    Stop the database keepalive service.
    Call this when your Flask app shuts down.
    """
    db_keepalive.stop()

# Alternative: Manual ping function for testing
def manual_database_ping():
    """
    Manually ping the database once.
    Useful for testing or one-off warming.
    """
    return db_keepalive.ping_database()