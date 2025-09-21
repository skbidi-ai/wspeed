import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import logging
import discord

logger = logging.getLogger(__name__)

class ModerationDB:
    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')
        if not self.db_url:
            raise ValueError("DATABASE_URL environment variable not set")
        
    def get_connection(self):
        """Get database connection with retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return psycopg2.connect(self.db_url, cursor_factory=RealDictCursor)
            except Exception as e:
                logger.error(f"Database connection attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    raise
                import time
                time.sleep(1)
    
    def init_database(self):
        """Initialize database tables"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Create moderation_actions table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS moderation_actions (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        moderator_id BIGINT NOT NULL,
                        server_id BIGINT NOT NULL,
                        action_type VARCHAR(20) NOT NULL,
                        reason TEXT NOT NULL,
                        duration_minutes INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP,
                        is_active BOOLEAN DEFAULT TRUE,
                        removed_by BIGINT,
                        removed_at TIMESTAMP,
                        removal_reason TEXT
                    )
                """)
                
                # Create indexes for better performance
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_moderation_user_id 
                    ON moderation_actions(user_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_moderation_server_id 
                    ON moderation_actions(server_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_moderation_active 
                    ON moderation_actions(is_active, expires_at)
                """)
                
                conn.commit()
                logger.info("Database tables initialized successfully")
    
    def add_moderation_action(self, user_id, moderator_id, server_id, action_type, reason, duration_minutes=None):
        """Add a new moderation action"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                expires_at = None
                if duration_minutes:
                    expires_at = datetime.utcnow() + timedelta(minutes=duration_minutes)
                
                cur.execute("""
                    INSERT INTO moderation_actions 
                    (user_id, moderator_id, server_id, action_type, reason, duration_minutes, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (user_id, moderator_id, server_id, action_type, reason, duration_minutes, expires_at))
                
                action_id = cur.fetchone()['id']
                conn.commit()
                return action_id
    
    def get_user_record(self, user_id, server_id):
        """Get all moderation actions for a user"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM moderation_actions 
                    WHERE user_id = %s AND server_id = %s
                    ORDER BY created_at DESC
                """, (user_id, server_id))
                
                return cur.fetchall()
    
    def get_active_actions(self, user_id, server_id, action_type=None):
        """Get active moderation actions for a user"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                query = """
                    SELECT * FROM moderation_actions 
                    WHERE user_id = %s AND server_id = %s AND is_active = TRUE
                    AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
                """
                params = [user_id, server_id]
                
                if action_type:
                    query += " AND action_type = %s"
                    params.append(action_type)
                
                query += " ORDER BY created_at DESC"
                cur.execute(query, params)
                
                return cur.fetchall()
    
    def remove_moderation_action(self, action_id, removed_by, removal_reason):
        """Remove/revoke a moderation action"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE moderation_actions 
                    SET is_active = FALSE, removed_by = %s, removed_at = CURRENT_TIMESTAMP, 
                        removal_reason = %s
                    WHERE id = %s AND is_active = TRUE
                    RETURNING *
                """, (removed_by, removal_reason, action_id))
                
                result = cur.fetchone()
                conn.commit()
                return result
    
    def cleanup_expired_actions(self):
        """Clean up expired moderation actions"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE moderation_actions 
                    SET is_active = FALSE 
                    WHERE is_active = TRUE 
                    AND expires_at IS NOT NULL 
                    AND expires_at <= CURRENT_TIMESTAMP
                    RETURNING id, user_id, action_type
                """)
                
                expired_actions = cur.fetchall()
                conn.commit()
                return expired_actions

# Global instance
mod_db = ModerationDB()