import psycopg2

try:
    # Connect to local PostgreSQL
    connection = psycopg2.connect(
        host="localhost",
        database="pharma_inventory",
        user="postgres",
        password="postgres"  # Use 'postgres' or leave empty string '' if needed
    )
    cursor = connection.cursor()

    # Define Schema
    create_tables_query = """
    CREATE TABLE IF NOT EXISTS medicines (
        medicine_id SERIAL PRIMARY KEY,
        generic_name VARCHAR(100) NOT NULL,
        brand_name VARCHAR(100) NOT NULL,
        category VARCHAR(50),
        minimum_stock_level INT DEFAULT 50,
        storage_requirements VARCHAR(255)
    );

    CREATE TABLE IF NOT EXISTS batches (
        batch_id VARCHAR(50) PRIMARY KEY,
        medicine_id INT REFERENCES medicines(medicine_id),
        supplier_name VARCHAR(100),
        quantity_in_stock INT NOT NULL,
        production_date DATE,
        expiration_date DATE NOT NULL,
        status VARCHAR(20) DEFAULT 'Active'
    );

    CREATE TABLE IF NOT EXISTS inventory_logs (
        log_id SERIAL PRIMARY KEY,
        batch_id VARCHAR(50) REFERENCES batches(batch_id),
        transaction_type VARCHAR(20) NOT NULL,
        quantity_changed INT NOT NULL,
        transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        handled_by VARCHAR(50)
    );
    """
    
    cursor.execute(create_tables_query)
    
    # Insert Initial Seed Data
    insert_mock_data = """
    INSERT INTO medicines (medicine_id, generic_name, brand_name, category, minimum_stock_level, storage_requirements)
    VALUES 
        (1, 'Amoxicillin', 'Amoxil', 'Antibiotic', 50, 'Store below 25°C in a dry place'),
        (2, 'Ibuprofen', 'Advai', 'Analgesic', 100, 'Store at room temperature 15-30°C'),
        (3, 'Metformin', 'Glucophage', 'Antidiabetic', 40, 'Protect from light and moisture')
    ON CONFLICT (medicine_id) DO NOTHING;

    INSERT INTO batches (batch_id, medicine_id, supplier_name, quantity_in_stock, production_date, expiration_date, status)
    VALUES 
        ('AMX-2026', 1, 'PharmaCorp', 15, '2025-01-10', '2026-12-31', 'Active'),
        ('IBU-9942', 2, 'HealthDistributors', 120, '2025-05-15', '2027-05-15', 'Active'),
        ('MET-5510', 3, 'GlobalMeds', 25, '2024-11-01', '2026-11-01', 'Active')
    ON CONFLICT (batch_id) DO NOTHING;
    """
    cursor.execute(insert_mock_data)

    connection.commit()
    print("✓ Schema initialized and seed data successfully inserted!")

except Exception as error:
    print("x Error connecting to database:", error)
finally:
    if 'connection' in locals() and connection:
        cursor.close()
        connection.close()