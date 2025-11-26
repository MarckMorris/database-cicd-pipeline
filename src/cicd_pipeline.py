#!/usr/bin/env python3
"""
Database CI/CD Pipeline
Automated schema changes with testing and rollback
"""

import psycopg2
import time
from datetime import datetime
import hashlib
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class DatabaseCICD:
    
    def __init__(self):
        self.dev_conn = None
        self.staging_conn = None
        self.prod_conn = None
        self.pipeline_runs = []
        
    def connect_all(self):
        """Connect to all environments"""
        try:
            self.dev_conn = psycopg2.connect(
                host='localhost', port=5451,
                dbname='dev_db', user='postgres', password='postgres'
            )
            self.dev_conn.autocommit = True
            
            self.staging_conn = psycopg2.connect(
                host='localhost', port=5452,
                dbname='staging_db', user='postgres', password='postgres'
            )
            self.staging_conn.autocommit = True
            
            self.prod_conn = psycopg2.connect(
                host='localhost', port=5453,
                dbname='prod_db', user='postgres', password='postgres'
            )
            self.prod_conn.autocommit = True
            
            logger.info("Connected to all environments")
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False
    
    def setup_pipeline_tracking(self):
        """Setup tables to track pipeline runs"""
        
        for conn, env in [(self.dev_conn, 'dev'), (self.staging_conn, 'staging'), 
                          (self.prod_conn, 'prod')]:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_versions (
                    version_id SERIAL PRIMARY KEY,
                    version_number VARCHAR(20),
                    description TEXT,
                    applied_at TIMESTAMP DEFAULT NOW(),
                    applied_by VARCHAR(100),
                    checksum VARCHAR(64)
                );
                
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id SERIAL PRIMARY KEY,
                    environment VARCHAR(20),
                    version_number VARCHAR(20),
                    status VARCHAR(20),
                    started_at TIMESTAMP DEFAULT NOW(),
                    completed_at TIMESTAMP,
                    error_message TEXT
                );
            """)
            cursor.close()
        
        logger.info("Pipeline tracking initialized")
    
    def create_migration(self, version: str, description: str, up_sql: str, down_sql: str):
        """Create a database migration"""
        
        checksum = hashlib.sha256(up_sql.encode()).hexdigest()
        
        return {
            'version': version,
            'description': description,
            'up_sql': up_sql,
            'down_sql': down_sql,
            'checksum': checksum
        }
    
    def apply_migration(self, conn, env: str, migration: dict) -> bool:
        """Apply migration to an environment"""
        
        cursor = conn.cursor()
        
        # Check if already applied
        cursor.execute("""
            SELECT version_number FROM schema_versions
            WHERE version_number = %s
        """, (migration['version'],))
        
        if cursor.fetchone():
            logger.info(f"  Migration {migration['version']} already applied to {env}")
            cursor.close()
            return True
        
        # Record pipeline run
        cursor.execute("""
            INSERT INTO pipeline_runs (environment, version_number, status)
            VALUES (%s, %s, 'running')
            RETURNING run_id
        """, (env, migration['version']))
        
        run_id = cursor.fetchone()[0]
        
        try:
            # Apply migration
            logger.info(f"  Applying migration {migration['version']} to {env}...")
            cursor.execute(migration['up_sql'])
            
            # Record version
            cursor.execute("""
                INSERT INTO schema_versions 
                (version_number, description, applied_by, checksum)
                VALUES (%s, %s, %s, %s)
            """, (migration['version'], migration['description'], 
                  'cicd-pipeline', migration['checksum']))
            
            # Update pipeline run
            cursor.execute("""
                UPDATE pipeline_runs
                SET status = 'success', completed_at = NOW()
                WHERE run_id = %s
            """, (run_id,))
            
            logger.info(f"  ✓ Migration {migration['version']} applied successfully")
            cursor.close()
            return True
            
        except Exception as e:
            logger.error(f"  ✗ Migration failed: {e}")
            
            # Update pipeline run with error
            cursor.execute("""
                UPDATE pipeline_runs
                SET status = 'failed', completed_at = NOW(), error_message = %s
                WHERE run_id = %s
            """, (str(e), run_id))
            
            cursor.close()
            return False
    
    def rollback_migration(self, conn, env: str, migration: dict) -> bool:
        """Rollback a migration"""
        
        logger.info(f"  Rolling back migration {migration['version']} on {env}...")
        
        cursor = conn.cursor()
        
        try:
            # Apply rollback SQL
            cursor.execute(migration['down_sql'])
            
            # Remove version record
            cursor.execute("""
                DELETE FROM schema_versions
                WHERE version_number = %s
            """, (migration['version'],))
            
            logger.info(f"  ✓ Rollback successful")
            cursor.close()
            return True
            
        except Exception as e:
            logger.error(f"  ✗ Rollback failed: {e}")
            cursor.close()
            return False
    
    def run_tests(self, conn, env: str) -> bool:
        """Run automated tests"""
        
        logger.info(f"  Running tests on {env}...")
        
        cursor = conn.cursor()
        
        tests = [
            ("Table exists", "SELECT to_regclass('users')"),
            ("Column exists", "SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'email'"),
            ("Index exists", "SELECT to_regclass('idx_users_email')"),
        ]
        
        all_passed = True
        
        for test_name, test_sql in tests:
            try:
                cursor.execute(test_sql)
                result = cursor.fetchone()
                
                if result and result[0]:
                    logger.info(f"    ✓ {test_name}: PASS")
                else:
                    logger.error(f"    ✗ {test_name}: FAIL")
                    all_passed = False
            except Exception as e:
                logger.error(f"    ✗ {test_name}: ERROR - {e}")
                all_passed = False
        
        cursor.close()
        
        if all_passed:
            logger.info(f"  ✓ All tests passed")
        else:
            logger.error(f"  ✗ Some tests failed")
        
        return all_passed
    
    def run_pipeline(self, migration: dict):
        """Run complete CI/CD pipeline"""
        
        print("\n" + "=" * 80)
        print(f"CI/CD PIPELINE: {migration['version']} - {migration['description']}")
        print("=" * 80)
        
        pipeline_success = True
        
        # Stage 1: Development
        print("\nSTAGE 1: DEVELOPMENT ENVIRONMENT")
        print("-" * 80)
        
        if not self.apply_migration(self.dev_conn, 'dev', migration):
            print("✗ Pipeline FAILED at DEV stage")
            return False
        
        if not self.run_tests(self.dev_conn, 'dev'):
            print("✗ Tests FAILED on DEV")
            self.rollback_migration(self.dev_conn, 'dev', migration)
            return False
        
        print("✓ DEV stage completed")
        time.sleep(2)
        
        # Stage 2: Staging
        print("\nSTAGE 2: STAGING ENVIRONMENT")
        print("-" * 80)
        
        if not self.apply_migration(self.staging_conn, 'staging', migration):
            print("✗ Pipeline FAILED at STAGING stage")
            return False
        
        if not self.run_tests(self.staging_conn, 'staging'):
            print("✗ Tests FAILED on STAGING")
            self.rollback_migration(self.staging_conn, 'staging', migration)
            return False
        
        print("✓ STAGING stage completed")
        time.sleep(2)
        
        # Stage 3: Production (with approval simulation)
        print("\nSTAGE 3: PRODUCTION ENVIRONMENT")
        print("-" * 80)
        print("  Simulating manual approval...")
        time.sleep(1)
        print("  ✓ Approval granted")
        
        if not self.apply_migration(self.prod_conn, 'prod', migration):
            print("✗ Pipeline FAILED at PROD stage")
            # Rollback staging too
            self.rollback_migration(self.staging_conn, 'staging', migration)
            return False
        
        if not self.run_tests(self.prod_conn, 'prod'):
            print("✗ Tests FAILED on PROD")
            print("  Initiating emergency rollback...")
            self.rollback_migration(self.prod_conn, 'prod', migration)
            return False
        
        print("✓ PROD stage completed")
        
        print("\n" + "=" * 80)
        print("✓ PIPELINE COMPLETED SUCCESSFULLY")
        print("=" * 80)
        
        return True
    
    def print_deployment_status(self):
        """Print current deployment status across environments"""
        
        print("\n" + "=" * 80)
        print("DEPLOYMENT STATUS")
        print("=" * 80)
        
        for conn, env in [(self.dev_conn, 'DEV'), (self.staging_conn, 'STAGING'), 
                          (self.prod_conn, 'PROD')]:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT version_number, description, applied_at
                FROM schema_versions
                ORDER BY applied_at DESC
                LIMIT 3
            """)
            
            versions = cursor.fetchall()
            
            print(f"\n{env} Environment:")
            if versions:
                for ver, desc, applied in versions:
                    print(f"  {ver}: {desc}")
                    print(f"    Applied: {applied}")
            else:
                print("  No migrations applied")
            
            cursor.close()
        
        print("=" * 80)
    
    def print_pipeline_history(self):
        """Print pipeline execution history"""
        
        print("\n" + "=" * 80)
        print("PIPELINE EXECUTION HISTORY")
        print("=" * 80)
        
        cursor = self.prod_conn.cursor()
        cursor.execute("""
            SELECT environment, version_number, status, started_at, 
                   completed_at, error_message
            FROM pipeline_runs
            ORDER BY started_at DESC
            LIMIT 10
        """)
        
        for row in cursor.fetchall():
            env, ver, status, started, completed, error = row
            
            duration = (completed - started).total_seconds() if completed else 0
            
            print(f"\n{env.upper()} - {ver}")
            print(f"  Status: {status.upper()}")
            print(f"  Duration: {duration:.2f}s")
            if error:
                print(f"  Error: {error}")
        
        cursor.close()
        print("=" * 80)
    
    def run_demo(self):
        """Run CI/CD pipeline demo"""
        
        print("\n" + "=" * 80)
        print("DATABASE CI/CD PIPELINE SYSTEM")
        print("=" * 80)
        
        if not self.connect_all():
            return
        
        self.setup_pipeline_tracking()
        
        # Migration 1: Create users table
        migration1 = self.create_migration(
            version='v1.0.0',
            description='Create users table',
            up_sql="""
                CREATE TABLE IF NOT EXISTS users (
                    user_id SERIAL PRIMARY KEY,
                    username VARCHAR(100),
                    email VARCHAR(100),
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX idx_users_email ON users(email);
            """,
            down_sql="""
                DROP INDEX IF EXISTS idx_users_email;
                DROP TABLE IF EXISTS users;
            """
        )
        
        self.run_pipeline(migration1)
        
        time.sleep(2)
        
        # Migration 2: Add status column
        migration2 = self.create_migration(
            version='v1.1.0',
            description='Add status column to users',
            up_sql="""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';
                CREATE INDEX idx_users_status ON users(status);
            """,
            down_sql="""
                DROP INDEX IF EXISTS idx_users_status;
                ALTER TABLE users DROP COLUMN IF EXISTS status;
            """
        )
        
        self.run_pipeline(migration2)
        
        # Print status
        self.print_deployment_status()
        self.print_pipeline_history()
        
        print("\n" + "=" * 80)
        print("Key Features:")
        print("  - Multi-environment deployment (Dev→Staging→Prod)")
        print("  - Automated testing at each stage")
        print("  - Automatic rollback on failure")
        print("  - Version tracking and history")
        print("  - Manual approval gates")
        print("=" * 80)


def main():
    pipeline = DatabaseCICD()
    pipeline.run_demo()


if __name__ == "__main__":
    main()
