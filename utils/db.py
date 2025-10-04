import os, time
# Swapped sqlite3 for pymysql and imported DictCursor
import pymysql.cursors 
from dotenv import load_dotenv

# Load environment variables to access MySQL credentials
load_dotenv() 

# DB_FILE is removed as connection details are in .env
SCHEMA_VERSION = 14 

def now(): return int(time.time())

def connect():
    """Establishes a connection to the MySQL database."""
    # Reads connection details from environment variables
    db_host = os.environ.get('MYSQL_HOST')
    db_user = os.environ.get('MYSQL_USER')
    db_password = os.environ.get('MYSQL_PASSWORD')
    db_name = os.environ.get('MYSQL_DB')
    
    # Establish connection
    con = pymysql.connect(
        host=db_host,
        user=db_user,
        password=db_password,
        database=db_name,
        # Use DictCursor to automatically return rows as dictionaries, replacing sqlite3.Row
        cursorclass=pymysql.cursors.DictCursor
    )
    return con

def to_dict(row):
    if not row: return None
    # DictCursor already returns a dict-like object
    return dict(row)

def init_db():
    print("DB init: Attempting to connect to MySQL and run migrations...")
    
    try:
        con = connect()
        cur = con.cursor()
    except Exception as e:
        print(f"DB init FAILED: Could not connect to MySQL. Error: {e}")
        return

    # --- Schema Version Tracking ---
    current_version = 0
    try:
        # Use MySQL types (INT NOT NULL PRIMARY KEY)
        cur.execute("CREATE TABLE IF NOT EXISTS schema_version (version INT NOT NULL PRIMARY KEY);")
        con.commit()
        
        cur.execute("SELECT version FROM schema_version;")
        r = cur.fetchone()

        if r is None:
            # Use %s placeholder for PyMySQL
            cur.execute("INSERT INTO schema_version (version) VALUES (%s);", (0,))
            con.commit()
            current_version = 0
        else:
            current_version = r['version']
    except Exception as e:
        print(f"Error accessing schema_version table. Please ensure the database is accessible. Error: {e}")
        # Proceed with caution if table access fails

    # --- Migration Logic (MySQL Syntax) ---

    if current_version < 1:
        # Create initial tables with MySQL data types (INT, FLOAT, VARCHAR/TEXT)
        cur.execute("""CREATE TABLE IF NOT EXISTS accounts (
            id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255) NOT NULL, exchange VARCHAR(255) NOT NULL,
            api_key_enc TEXT NOT NULL, api_secret_enc TEXT NOT NULL, testnet INT DEFAULT 1, active INT DEFAULT 1,
            futures_balance FLOAT, created_at INT, updated_at INT );""")
        cur.execute("""CREATE TABLE IF NOT EXISTS bots (
            id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255) NOT NULL, account_id INT NOT NULL,
            symbol VARCHAR(255) NOT NULL, long_enabled INT, long_amount FLOAT, long_leverage INT,
            short_enabled INT, short_amount FLOAT, short_leverage INT, r_points_json TEXT,
            cond_sl_close INT, cond_trailing INT, cond_close_last INT, start_time INT,
            long_entry_price FLOAT, short_entry_price FLOAT, long_status VARCHAR(50), short_status VARCHAR(50),
            long_sl_point FLOAT, short_sl_point FLOAT, testnet INT, margin_type VARCHAR(50) DEFAULT 'ISOLATED',
            long_final_roi FLOAT DEFAULT 0.0, short_final_roi FLOAT DEFAULT 0.0 );""")
        cur.execute("""CREATE TABLE IF NOT EXISTS templates (
            id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255) NOT NULL, symbol VARCHAR(255), long_enabled INT,
            long_amount FLOAT, long_leverage INT, short_enabled INT, short_amount FLOAT, short_leverage INT,
            r_points_json TEXT, cond_sl_close INT, cond_trailing INT, cond_close_last INT, created_at INT );""")
        con.commit()

    if current_version < 5:
        # Use VARCHAR(50) for margin_type in templates
        try: cur.execute("ALTER TABLE templates ADD COLUMN margin_type VARCHAR(50) DEFAULT 'ISOLATED'")
        except Exception as e: print(f"Migration v5 failed (templates.margin_type): {e}")
        con.commit()
    
    if current_version < 6:
        new_columns = [ 
            "time_frame VARCHAR(50) DEFAULT '1m'", "trade_mode VARCHAR(50) DEFAULT 'Follow'", "run_mode VARCHAR(50) DEFAULT 'Ongoing'",
            "recovery_margin FLOAT DEFAULT 5", "max_trades INT DEFAULT 0", "open_on_new_candle INT DEFAULT 1",
            "close_on_candle_end INT DEFAULT 0" 
        ]
        for table in ['bots', 'templates']:
            for col in new_columns:
                try: cur.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
                except Exception as e: print(f"Migration v6 for {table} failed ({col}): {e}")
        con.commit()

    if current_version < 7:
        for table in ['bots', 'templates']:
            try: cur.execute(f"ALTER TABLE {table} ADD COLUMN trade_amount_mode VARCHAR(50) DEFAULT 'Normal'")
            except Exception as e: print(f"Migration v7 for {table} failed: {e}")
        con.commit()
        
    if current_version < 8:
        stat_columns = [
            "total_trades INT DEFAULT 0", "winning_trades INT DEFAULT 0", "losing_trades INT DEFAULT 0",
            "breakeven_trades INT DEFAULT 0", "total_pnl FLOAT DEFAULT 0.0" 
        ]
        for col in stat_columns:
            try: cur.execute(f"ALTER TABLE bots ADD COLUMN {col}")
            except Exception as e: print(f"Migration v8 failed ({col}): {e}")
        con.commit()
            
    if current_version < 9:
        for table in ['bots', 'templates']:
            try: cur.execute(f"ALTER TABLE {table} ADD COLUMN recovery_max_amount FLOAT DEFAULT 0")
            except Exception as e: print(f"Migration v9 for {table} failed: {e}")
        con.commit()
        
    if current_version < 10:
        for table in ['bots', 'templates']:
            try: cur.execute(f"ALTER TABLE {table} ADD COLUMN current_trade_amount FLOAT DEFAULT 0")
            except Exception as e: print(f"Migration v10 for {table} failed: {e}")
        con.commit()
        
    if current_version < 11:
        stat_columns_v11 = ["total_profit FLOAT DEFAULT 0.0", "total_loss FLOAT DEFAULT 0.0"]
        for col in stat_columns_v11:
            try: cur.execute(f"ALTER TABLE bots ADD COLUMN {col}")
            except Exception as e: print(f"Migration v11 failed ({col}): {e}")
        con.commit()
            
    if current_version < 12:
        try: cur.execute("ALTER TABLE bots ADD COLUMN paused INT DEFAULT 0")
        except Exception as e: print(f"Migration v12 failed: {e}")
        con.commit()

    # --- Migration v13: Add user_id to bots and templates for Multi-Tenancy ---
    if current_version < 13:
        new_column = "user_id INT NOT NULL"
        for table in ['bots', 'templates']:
            try: cur.execute(f"ALTER TABLE {table} ADD COLUMN {new_column}")
            except Exception as e: print(f"Migration v13 for {table} failed ({new_column}): {e}")
        con.commit()

    # --- Migration v14: Add user_id to accounts for Multi-Tenancy ---
    if current_version < 14:
        new_column = "user_id INT NOT NULL"
        try: cur.execute(f"ALTER TABLE accounts ADD COLUMN {new_column}")
        except Exception as e: print(f"Migration v14 for accounts failed ({new_column}): {e}")
        con.commit()

    if current_version < SCHEMA_VERSION:
        cur.execute("UPDATE schema_version SET version=%s;", (SCHEMA_VERSION,))
        con.commit()

    con.close()
    print(f"DB init OK. Schema version is now {SCHEMA_VERSION}.")