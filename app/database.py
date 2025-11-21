"""
資料庫連線配置
"""
import os
from sqlalchemy import create_engine, text  # 新增 text 匯入以支援 SQLAlchemy 2.0
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool

# ==========================================
# 從環境變數讀取資料庫配置
# ==========================================
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = os.getenv('POSTGRES_PORT', '5432')
POSTGRES_USER = os.getenv('POSTGRES_USER', 'loguser')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'logpass')
POSTGRES_DB = os.getenv('POSTGRES_DB', 'logsdb')

# ==========================================
# 資料庫連線 URL
# ==========================================
# 同步連線 URL (用於 Worker)
DATABASE_URL = (
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# 非同步連線 URL (用於 FastAPI)
ASYNC_DATABASE_URL = (
    f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# ==========================================
# 同步引擎 (Worker 使用)
# ==========================================
sync_engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,           # 常駐連線數
    max_overflow=5,         # 額外連線數
    pool_timeout=30,        # 等待連線超時
    pool_recycle=3600,      # 連線回收時間（1小時）
    pool_pre_ping=True,     # 使用前先測試連線
    echo=False              # 不輸出 SQL（生產環境）
)

# 同步 Session
SyncSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=sync_engine
)

# ==========================================
# 非同步引擎 (FastAPI 使用)
# ==========================================
async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    pool_size=10,
    max_overflow=5,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True,
    echo=False
)

# 非同步 Session
AsyncSessionLocal = sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# ==========================================
# ORM Base
# ==========================================
Base = declarative_base()

# ==========================================
# 依賴注入函數
# ==========================================
async def get_async_db():
    """
    FastAPI 依賴注入：提供非同步資料庫 Session
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

def get_sync_db():
    """
    Worker 使用：提供同步資料庫 Session
    """
    db = SyncSessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# ==========================================
# 資料庫初始化
# ==========================================
async def init_db():
    """
    初始化資料庫（建立所有表格）
    """
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# ==========================================
# 連線測試
# ==========================================
async def test_db_connection():
    """
    測試資料庫連線是否正常
    """
    try:
        async with AsyncSessionLocal() as session:
            # 原始寫法:直接傳遞字串 "SELECT 1" 給 execute()
            # await session.execute("SELECT 1")
            # 修正:SQLAlchemy 2.0+ 要求使用 text() 包裝文字 SQL
            await session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"資料庫連線失敗: {e}")
        return False
