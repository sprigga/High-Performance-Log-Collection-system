# PostgreSQL 連線池 (Connection Pool) 的設置與作用

PostgreSQL 的連線池 (Connection Pool) 是這個系統中確保資料庫效能和穩定性的關鍵元件。

---

### 1. 為什麼需要連線池？問題與比喻

**問題**：每一次應用程式需要與資料庫溝通時，如果都建立一個新的連線，會非常耗時且消耗資源。這個過程包括：
1.  建立網路 TCP 連線。
2.  PostgreSQL 伺服器驗證使用者名稱和密碼。
3.  伺服器分配記憶體並建立一個新的後端程序 (backend process) 來處理這個連線。

在高併發的系統中，頻繁地建立和銷毀連線會迅速耗盡伺服器資源，並導致嚴重的效能瓶頸。

**比喻**：您可以把**連線池**想像成一個**計程車招呼站**。
*   **沒有連線池**：每次你需要出門時，都打電話叫一輛全新的車，等它從工廠生產出來、送到你面前，用完後再把它報廢。這顯然非常沒有效率。
*   **有連線池**：在招呼站（連線池）裡，總是有**一定數量的計程車（資料庫連線）在待命**。你需要用車時，直接從站裡開走一輛。用完後，你不是把車報廢，而是**把它開回招呼站**，讓下一個人可以繼續使用。

---

### 2. 連線池在您專案中的設定 (`app/database.py`)

在您的專案中，連線池是由 **SQLAlchemy** 的 `Engine` 物件自動管理的。主要的設定位於 `app/database.py` 檔案中。

```python
# app/database.py

# 同步引擎 (Worker 使用)
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

# 非同步引擎 (FastAPI 使用)
async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    pool_size=10,
    max_overflow=5,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True,
    echo=False
)
```

這些參數的作用如下 (繼續使用計程車比喻)：

*   **`pool_size=10`**: 招呼站裡平時固定有 **10 輛計程車**在待命。這是連線池的核心，這些連線會被保持開放以便快速重複使用。

*   **`max_overflow=5`**: 如果 10 輛車都被開走了，但突然又來了更多客人，招呼站最多可以**額外再叫 5 輛臨時的計程車**來應急。這些臨時連線在使用完畢後會被關閉，而不會立刻回到池中。這意味著系統最多可以同時處理 `10 + 5 = 15` 個資料庫請求。

*   **`pool_timeout=30`**: 如果 15 輛車全都在外面跑，你作為一個新來的客人，最多願意**等待 30 秒**。如果在 30 秒內有車回來，你就可以坐上。如果等了 30 秒還沒有車，系統就會放棄並報錯 (TimeoutError)，而不是無限期地等待。

*   **`pool_recycle=3600`**: 為了防止計程車開太久變舊（例如，因為網路防火牆超時而斷線），系統規定每輛車**每 3600 秒（1小時）**就必須回廠保養一次。SQLAlchemy 會自動將超過這個時間的閒置連線關閉並替換成新的，確保連線的有效性。

*   **`pool_pre_ping=True`**: 在你坐上計程車之前，司機會先點火測試一下引擎是否正常 (發送一個類似 `SELECT 1` 的簡單查詢)。這可以有效地防止你拿到一輛已經「熄火」（失效）的連線，大大提高了系統的穩定性，雖然會增加極小的開銷。

---

### 3. 連線池的實際作用與使用方式

連線池建立好之後，應用程式通過 **Session** 來使用它。Session 是與資料庫進行所有互動（查詢、新增、刪除等）的窗口。

#### a) 在 FastAPI 中 (非同步)

FastAPI 使用**依賴注入 (Dependency Injection)** 的方式來管理 Session，這非常優雅。

*   **`get_async_db` 函數 (`app/database.py`)**:
    ```python
    async def get_async_db():
        async with AsyncSessionLocal() as session:
            yield session
            await session.commit() # 交易提交
        except Exception:
            await session.rollback() # 交易回滾
            raise
        finally:
            await session.close() # 釋放 Session，連線回歸連線池
    ```
    當一個 API 請求進來時，FastAPI 會呼叫 `get_async_db`。`async with AsyncSessionLocal() as session:` 這行程式碼會**自動從 `async_engine` 的連線池中取出一個連線**，並建立一個 Session。當 API 請求處理完畢（無論成功或失敗），`with` 區塊結束，SQLAlchemy 會**自動將連線釋放回連線池**，而不是關閉它。

#### b) 在 Worker 中 (同步)

同步的 Worker 使用更傳統的 `try...finally` 模式來確保連線的釋放。

*   **`get_sync_db` 函數 (`app/database.py`)**:
    ```python
    def get_sync_db():
        db = SyncSessionLocal()
        try:
            yield db
            db.commit() # 交易提交
        except Exception:
            db.rollback() # 交易回滾
            raise
        finally:
            db.close() # 釋放 Session，連線回歸連線池
    ```
    `db = SyncSessionLocal()` 會**從 `sync_engine` 的連線池中取出一個連線**並建立 Session。在 `finally` 區塊中，`db.close()` 是**最關鍵的一步**。它並**不是真的關閉資料庫連線**，而是**將這個連線歸還給連線池**，以便後續的任務可以重複使用。

---

### 4. 總結

PostgreSQL 連線池是您系統效能的基石。它通過**重複使用**現有的資料庫連線，避免了昂貴的連線建立開銷，同時通過詳細的參數設定來管理資源和應對高併發流量，最終為您的應用程式提供了**高效、穩定、可擴展**的資料庫存取能力。
