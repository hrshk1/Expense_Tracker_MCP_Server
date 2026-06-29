from fastmcp import FastMCP
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "expenses.db")
CATEGORIES_PATH = os.path.join(os.path.dirname(__file__), "categories.json")

mcp = FastMCP("Expense Tracker MCP Server", "1.0.0")

def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS expenses (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT NOT NULL,
                        amount REAL NOT NULL,
                        category TEXT NOT NULL,
                        subcategory TEXT DEFAULT '',
                        note TEXT DEFAULT ''
                    )""")
        
init_db()


@mcp.tool()
def add_expense(date,amount,category,subcategory='',note=''):
    """Add a new expense to the database."""
    with sqlite3.connect(DB_PATH) as c:
        curr = c.execute("INSERT INTO expenses (date, amount, category, subcategory, note) VALUES (?, ?, ?, ?, ?)",
                         (date, amount, category, subcategory, note))
        return {"status": "success", "id": curr.lastrowid}
    
@mcp.tool()
def list_expenses(start_date, end_date):
    '''List expense entries within an inclusive date range.'''
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute(
            """
            SELECT id, date, amount, category, subcategory, note
            FROM expenses
            WHERE date BETWEEN ? AND ?
            ORDER BY id ASC
            """,
            (start_date, end_date)
        )

        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


@mcp.tool()
def summarize_expenses_by_category(category):
    """Summarize expenses for a given category."""

    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute(
            """
            SELECT
                category,
                COUNT(*) AS total_transactions,
                SUM(amount) AS total_amount,
                AVG(amount) AS average_amount,
                MIN(amount) AS minimum_amount,
                MAX(amount) AS maximum_amount
            FROM expenses
            WHERE category = ?
            GROUP BY category
            """,
            (category,)
        )

        row = cur.fetchone()

        if row is None:
            return {
                "message": f"No expenses found for category '{category}'."
            }

        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    
@mcp.resource("expense://categories", mime_type="application/json")
def get_categories():
    #
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
    
    