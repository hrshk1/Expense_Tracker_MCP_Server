from fastmcp import FastMCP
import aiofiles
import aiosqlite
import os
from contextlib import asynccontextmanager

from auth import create_auth_provider, require_reader, require_writer

APP_DIR = os.path.dirname(__file__)
CATEGORIES_PATH = os.path.join(os.path.dirname(__file__), "categories.json")

mcp = FastMCP(
    "Expense Tracker MCP Server",
    version="1.0.0",
    auth=create_auth_provider(),
)


def get_db_path():
    explicit_path = os.getenv("EXPENSE_DB_PATH")
    if explicit_path:
        return os.path.abspath(explicit_path)

    data_dir = os.getenv("EXPENSE_DATA_DIR")
    if data_dir:
        return os.path.join(os.path.abspath(data_dir), "expenses.db")

    local_db_path = os.path.join(APP_DIR, "expenses.db")
    local_db_is_writable = not os.path.exists(local_db_path) or os.access(local_db_path, os.W_OK)
    if os.access(APP_DIR, os.W_OK) and local_db_is_writable:
        return local_db_path

    return os.path.join("/tmp", "expense_tracker_mcp_server", "expenses.db")


DB_PATH = get_db_path()
DB_INITIALIZED = False


@asynccontextmanager
async def connect_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db():
    global DB_INITIALIZED

    async with connect_db() as c:
        await c.execute("""CREATE TABLE IF NOT EXISTS expenses (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT NOT NULL,
                        amount REAL NOT NULL,
                        category TEXT NOT NULL,
                        subcategory TEXT DEFAULT '',
                        note TEXT DEFAULT ''
                    )""")
        await c.commit()
    DB_INITIALIZED = True


async def ensure_db_initialized():
    if not DB_INITIALIZED:
        await init_db()


@mcp.tool(auth=require_writer)
async def add_expense(date, amount, category, subcategory='', note=''):
    """Add a new expense to the database."""
    await ensure_db_initialized()

    async with connect_db() as c:
        curr = await c.execute(
            "INSERT INTO expenses (date, amount, category, subcategory, note) VALUES (?, ?, ?, ?, ?)",
            (date, amount, category, subcategory, note)
        )
        await c.commit()
        return {"status": "success", "id": curr.lastrowid}


@mcp.tool(auth=require_reader)
async def list_expenses(start_date, end_date):
    '''List expense entries within an inclusive date range.'''
    await ensure_db_initialized()

    async with connect_db() as c:
        cur = await c.execute(
            """
            SELECT id, date, amount, category, subcategory, note
            FROM expenses
            WHERE date BETWEEN ? AND ?
            ORDER BY id ASC
            """,
            (start_date, end_date)
        )

        rows = await cur.fetchall()
        return [dict(row) for row in rows]


@mcp.tool(auth=require_reader)
async def summarize_expenses_by_category(category):
    """Summarize expenses for a given category."""
    await ensure_db_initialized()

    async with connect_db() as c:
        cur = await c.execute(
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

        row = await cur.fetchone()

        if row is None:
            return {
                "message": f"No expenses found for category '{category}'."
            }

        return dict(row)


@mcp.resource("expense://categories", mime_type="application/json")
async def get_categories():
    async with aiofiles.open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        return await f.read()


if __name__ == "__main__":
    import asyncio

    asyncio.run(init_db())
    mcp.run(transport="http", host="0.0.0.0", port=8000)
