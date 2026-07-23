import logging
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient
from diabetic.config import config

class DatabaseSingleton:
    """
    Shared MongoDB client singleton to prevent Atlas connection exhaustion.
    Centralizes connection pooling and collection management.
    """
    _instance: Optional['DatabaseSingleton'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseSingleton, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self.logger = logging.getLogger("Bio-Quant.Utils.DB")
        # Prioritize MONGODB_URI (Heroku Addons) over MONGO_URI (Local/Manual)
        self.uri = config.MONGODB_URI or config.MONGO_URI
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None
        
        # Collections
        self.entries = None
        self.treatments = None
        self.audit_logs = None
        self.environment_history = None
        self.cardiac_history = None
        
        if self.uri:
            try:
                # maxPoolSize=10 to stay within Atlas free/shared tier limits
                # serverSelectionTimeoutMS=5000 to prevent long hangs on startup
                self.client = AsyncIOMotorClient(
                    self.uri, 
                    maxPoolSize=10, 
                    serverSelectionTimeoutMS=5000,
                    socketTimeoutMS=20000,
                    heartbeatFrequencyMS=10000
                )
                
                # Deterministic DB Name resolution
                db_name = self.uri.split('/')[-1].split('?')[0] or "nightscout"
                self.db = self.client[db_name]
                
                # Standard Nightscout Collections
                self.entries = self.db["entries"]
                self.treatments = self.db["treatments"]
                
                # Bio-Quant Specific Collections (can be in same DB for consolidation)
                self.audit_logs = self.db["audit_logs"]
                self.environment_history = self.db["environment_history"]
                self.cardiac_history = self.db["cardiac_history"]
                
                self.logger.info(f"MongoDB Singleton initialized: {db_name} (Pool: 10)")
                self._initialized = True
            except Exception as e:
                self.logger.error(f"Failed to initialize MongoDB Singleton: {e}")
        else:
            self.logger.warning("MONGO_URI missing. Persistent cloud operations disabled.")

    async def ensure_indices(self):
        """Creates high-performance indices for common query patterns."""
        if not self._initialized:
            return
            
        try:
            # Entries: date is the primary query key
            await self.entries.create_index([("date", -1)])
            
            # Treatments: created_at used for windowing
            await self.treatments.create_index([("created_at", -1)])
            
            # Audit Logs: event_type and timestamp
            await self.audit_logs.create_index([("event_type", 1), ("timestamp", -1)])
            
            # Environment History: timestamp for joining/windowing
            await self.environment_history.create_index([("timestamp", -1)])
            await self.cardiac_history.create_index([("timestamp", -1)])
            
            self.logger.info("MongoDB indices verified/created.")
        except Exception as e:
            self.logger.error(f"Failed to create database indices: {e}")

    async def close(self):
        """Closes the underlying MongoDB connection pool."""
        if self.client:
            self.client.close()
            self.logger.info("MongoDB Singleton shut down.")

# Global Accessor
db_manager = DatabaseSingleton()
