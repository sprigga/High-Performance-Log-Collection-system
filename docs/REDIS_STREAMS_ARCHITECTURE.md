# Redis Stream 架構：`logs:stream` 與 `log_workers`

`logs:stream` 和 `log_workers` 是系統中實現**異步任務處理**和**高可靠性**的關鍵，它們共同構成了一個基於 Redis Stream 的生產者-消費者模式。

可以將 `logs:stream` 想像成一條**生產線的傳送帶**，而 `log_workers` 則是這條傳送帶旁邊的**一群工人**。

---

### `logs:stream` 的角色：任務傳送帶

`logs:stream` 是在 Redis 中建立的一個 **Stream (串流)** 資料結構。

*   **本質**：一個**持久化的、只能追加 (append-only) 的日誌**。您可以把它看作一個先進先出 (FIFO) 的任務佇列 (Task Queue)，但功能更強大。

*   **生產者 (Producer)**：
    *   **FastAPI 應用 (`app/main.py`)**。
    *   當 FastAPI 伺服器接收到一筆新的日誌時，它會使用 Redis 的 `XADD` 命令把它「放」到 `logs:stream` 這條傳送帶的末端。
    *   這個動作非常快，所以 FastAPI 可以立刻回應客戶端，而不需要等待日誌被真正處理完。

*   **程式碼示例 (`app/main.py`)**：
    ```python
    # 在 create_log 函數中
    message_id = await redis_client.xadd(
        name="logs:stream", # <-- 指定了 Stream 的名稱
        fields=log_dict
    )
    ```

---

### `log_workers` 的角色：工人團隊

`log_workers` 並不是一個實際的程式或實體，它是一個 **消費者群組 (Consumer Group)** 的**名稱**。

*   **本質**：一個標籤或團隊名稱，用於組織一群共同處理 `logs:stream` 中任務的消費者。

*   **消費者 (Consumer)**：
    *   **背景 Worker 程式 (`app/worker.py`)**。
    *   每一個運行的 `worker.py` 程式就是一個「工人」。當工人啟動時，它會向 Redis 註冊自己，表示「我是 `log_workers` 這個團隊的一員」。

*   **程式碼示例 (`app/main.py` 或 `app/worker.py`)**：
    系統在啟動時會確保這個消費者群組存在。
    ```python
    # 在 startup_event 或 init_redis 中
    await redis_client.xgroup_create(
        name='logs:stream',      # <-- 為哪個 Stream 服務
        groupname='log_workers', # <-- 團隊的名稱
        id='0',
        mkstream=True
    )
    ```

---

### 協同運作方式

1.  **生產任務**：FastAPI (生產者) 通過 `XADD` 將一筆日誌（任務）放到 `logs:stream` 傳送帶上。

2.  **領取任務**：一個空閒的 Worker (消費者) 會執行 `XREADGROUP` 命令。這個命令的語意是：「**我是 `log_workers` 團隊的成員，請從 `logs:stream` 傳送帶上拿一個我們團隊還沒有處理過的新任務給我。**」

3.  **協同工作與負載均衡**：Redis 會確保傳送帶上的**每一條任務只會被分配給 `log_workers` 團隊中的一名成員**。如果您啟動了 3 個 Worker，Redis 就會自動將任務分發給這 3 個工人，實現了自動的負載均衡。

4.  **處理與確認 (ACK)**：
    *   工人拿到任務（日誌資料）後，開始執行耗時的操作（例如將資料寫入 PostgreSQL）。
    *   當工作**成功完成**後，工人會向 Redis 發送一個 `XACK` (Acknowledge) 命令，意思是：「報告！我已經處理完這條任務了，你可以把它從待辦清單中劃掉了。」

5.  **可靠性與故障轉移**：
    *   如果一個工人在處理任務的過程中**不幸崩潰了，且未來得及發送 `XACK` 確認**，那麼這條任務在 Redis 中會處於「待處理 (Pending)」狀態。
    *   `log_workers` 群組的其他健康工人可以發現這條「待處理」了很久的任務，並將其**重新領取**來處理，從而確保即使有單一工人故障，日誌資料也不會遺失。

### 總結

| 元件 | 比喻 | 作用 | 主要 Redis 命令 |
| :--- | :--- | :--- | :--- |
| **`logs:stream`** | 任務傳送帶 | 作為日誌資料的持久化佇列，解耦生產者和消費者。 | `XADD` |
| **`log_workers`** | 工人團隊 | 一個消費者群組的名稱，允許多個 Worker 協同工作並提供可靠性。 | `XGROUP CREATE` |
| **`app/worker.py`** | 工人 | 實際執行任務的背景程式，從 Stream 中讀取資料並處理。 | `XREADGROUP`, `XACK` |

這個「傳送帶 + 工人團隊」的架構，使得您的日誌收集系統既**高效**（FastAPI能快速響應），又**可擴展**（可以隨時增減工人數量），還非常**可靠**（即使工人故障也不會丟失資料）。
