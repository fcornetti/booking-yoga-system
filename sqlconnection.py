import pyodbc

# List all available drivers
drivers = pyodbc.drivers()
print("Available ODBC drivers:")
for driver in drivers:
    print(f"- {driver}")

# Connection parameters
server = 'jantinevanwijlickserver.database.windows.net'
database = 'jantinevanwijlickdb'
username = 'jantinevanwijlick'
password = 'Gohxo7-foggog-'
driver = '{ODBC Driver 18 for SQL Server}'  # Check your installed drivers

# Create connection string
conn_string = f'DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password}'

# Connect to the database
try:
    conn = pyodbc.connect(conn_string)
    cursor = conn.cursor()

    # Create a simple table if it doesn't exist
    '''create_table_query = """
    IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'SampleTable')
    BEGIN
        CREATE TABLE SampleTable (
            ID INT PRIMARY KEY IDENTITY(1,1),
            Name NVARCHAR(100),
            Email NVARCHAR(100),
            CreatedDate DATETIME DEFAULT GETDATE()
        )
        
        -- Insert some sample data
        INSERT INTO SampleTable (Name, Email) VALUES
            ('John Doe', 'john.doe@example.com'),
            ('Jane Smith', 'jane.smith@example.com'),
            ('Bob Johnson', 'bob.johnson@example.com'),
            ('Alice Williams', 'alice.williams@example.com'),
            ('David Brown', 'david.brown@example.com')
    END
    """

    cursor.execute(create_table_query)
    conn.commit()
    print("Table created successfully if it didn't exist before.")'''

    # Query the newly created table
    cursor.execute("SELECT TOP 10 * FROM SampleTable")
    rows = cursor.fetchall()

    for row in rows:
        print(row)

    # Close the connection
    cursor.close()
    conn.close()
    print("Connection closed successfully.")

except Exception as e:
    print(f"Error connecting to database: {e}")