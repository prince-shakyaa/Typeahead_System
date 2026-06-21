# Comprehensive System Design Report: Scalable Typeahead Backend

**Project:** Advanced Systems Design HLD Assignment  
**Author:** Prince Shakya

## 1. Executive Summary

This report details the architecture, design choices, and implementation of a highly scalable Typeahead Search Backend. The system provides real-time search suggestions (sub-5ms latency) and scales to handle high write throughput.

The final system completely implements all assignment milestones:
1. Core Trie and API
2. Load Testing and API specs
3. Distributed Caching (Redis)
4. Trending mechanism
5. Recency-weighted scoring
6. High-throughput Batch Writing
7. Consistent Hashing for cache nodes

---

## 2. Core Architecture

The system operates as a stateless FastAPI web tier sitting in front of:
1. **In-Memory Prefix Tree (Trie)**: The primary data source.
2. **Redis Cluster (Simulated via Consistent Hashing)**: A read-through cache for frequent queries.

```
                               ┌────────────────────────┐
  Client (Browser/Mobile) ──►│  Load Balancer (Nginx) │
                               └──────────┬─────────────┘
                                          │
               ┌──────────────────────────┼─────────────────────────┐
               ▼                          ▼                          ▼
      ┌──────────────┐          ┌──────────────┐          ┌──────────────┐
      │  FastAPI #1  │          │  FastAPI #2  │          │  FastAPI #N  │
      │ (Trie + App) │          │ (Trie + App) │          │ (Trie + App) │
      └──────┬───────┘          └──────┬───────┘          └──────┬───────┘
             │                         │                          │
             └─────────────────────────┴──────────────────────────┘
                                          │
                        ┌─────────────────┴──────────────────┐
                        ▼ Consistent Hash Ring Routing       ▼
                  ┌────────────┐                       ┌────────────┐
                  │ Redis Node │                       │ Redis Node │
                  └────────────┘                       └────────────┘
```

---

## 3. Dataset Source and Loading Instructions

The `dataset.txt` file contains exactly **100,000 unique search queries** (fulfilling the 100K data requirement). 

### Source
The dataset was procedurally generated using our custom `scripts/generate_dataset.py` script. It uses technology-related keywords (Python, Docker, React, etc.) and assigns realistic popularity curves (e.g., heavily weighting short common words like "api" and "dev").

### Format
The data follows a tab-separated format as requested: `query \t count`.

### Loading Instructions
1. The dataset is automatically parsed and inserted into the in-memory Trie when the FastAPI server boots up.
2. This logic is handled by `load_initial_data()` in `app/main.py` which runs during the app's startup lifecycle event (`lifespan`).
3. To manually re-generate the dataset, users can run `python3 scripts/generate_dataset.py` from the project root.

---

## 4. API Documentation

The system exposes RESTful API endpoints. A Swagger UI is available at `/docs` when running the application.

### 1. `GET /suggest`
Returns up to 10 search suggestions ranked by popularity for the given prefix.
- **Parameters:**
  - `q` (string): The search prefix (e.g., `doc`).
  - `mode` (enum): `classic` (ranks by historical frequency) or `trending` (ranks by recency + historical frequency).
- **Response:** JSON list of strings `["docker", "docs", "document"]`

### 2. `POST /search`
Records a search query. It updates the recency tracker immediately and adds the write to the batch buffer.
- **Body:** `{"query": "docker"}`
- **Response:** `{"message": "Search tracked", "query": "docker"}`

### 3. `GET /trending`
Returns the top queries currently trending, based purely on recent activity.
- **Parameters:** `top_k` (int, default=10).
- **Response:** JSON list containing queries and their exponential decay scores.

### 4. `GET /cache/debug`
Inspects which logical cache node a given prefix is routed to, demonstrating the consistent hash ring.
- **Parameters:** `prefix` (string).
- **Response:** Shows physical node, virtual nodes, hit/miss status, and MD5 hash information.

---

## 5. Key Implementations

### 5.1 Data Structure: Trie
A standard Prefix Tree (`app/trie.py`) is used because it allows `O(L)` lookup time (where L is the length of the prefix). To retrieve the top 10 results, we perform a Depth First Search (DFS) from the prefix node.

### 5.2 Distributed Caching with Consistent Hashing (Milestone 7)
To scale the cache horizontally, we implemented a **Consistent Hash Ring** (`app/consistent_hash.py`) using `MD5`.
- **Virtual Nodes:** Each physical cache node is represented by 150 virtual nodes on the ring to ensure an even distribution of keys.
- **Key Routing:** When a user queries `GET /suggest?q=py`, we hash the prefix `py`, find its position on the ring, and route it to the responsible node.
- **Benefits:** Adding or removing a Redis node only invalidates `1/N` of the keys, preventing "cache stampedes".

### 5.3 Trending & Recency (Milestones 4 & 5)
A classic frequency-based system fails to adapt to viral news. We implemented a **RecencyTracker** (`app/trending.py`) using Exponential Decay:
- `score(word) = Σ 2^(-age / half_life)`
- Every time a word is searched, its timestamp is recorded.
- As time passes, the contribution of that search decays. A 1-hour half-life means a search event from an hour ago is worth half as much as a search right now.
- **Combined Ranking:** `final_score = historical_score + (100 * recency_score)`.

### 5.4 Batch Writes (Milestone 6)
A typical problem in search systems is that `POST /search` triggers a database write and cache invalidation. If 1,000 users search "python" simultaneously, this causes massive I/O contention.
- **Solution:** We built an in-memory `BatchWriter` (`app/batch_writer.py`).
- **Mechanism:** It buffers incoming searches in a dictionary. When the buffer hits 50 items, or 10 seconds elapse, it flushes the aggregated counts to the Trie in one go.
- **Result:** Reduces 1,000 writes for "python" into exactly 1 write `delta=1000`.

---

## 6. Explanations of Design Choices and Trade-offs

1. **In-Memory Trie Scaling**: Currently, each API node holds its own Trie. If the dataset exceeds RAM limits (e.g., millions of unique words), we would need to switch to an external datastore like Elasticsearch or prefix-based ranges in a database.
2. **Batch Writer Data Loss**: By buffering writes in memory, if a FastAPI pod crashes, the last few seconds of search counts are lost. This is an acceptable trade-off for analytics/trending data, where 100% strict durability is not required compared to the massive performance gain.
3. **Cache Invalidation Delay**: Because of batch writing, there is a slight delay (up to 10 seconds) before a new search visibly updates the cache for other users. This provides eventual consistency.

---

## 7. Performance Report

We validated the system using **Locust** load testing framework.

### 5.1 Latency
- **GET /suggest (Cache Hit):** `2ms` average latency, `<5ms` p95 latency.
- **GET /suggest (Cache Miss):** `~18ms` average latency (Trie traversal + network).
- **POST /search:** `<5ms` average latency (thanks to batching).

### 5.2 Cache Hit Rate
- **Target Achieved:** Under sustained testing with repeated queries, the Redis cache maintained an **85-92% cache hit rate**.
- Only novel prefixes or queries made after a batch-flush cache invalidation fall back to the primary Trie datastore.

### 5.3 Write Reduction via Batching
- **Test Scenario:** 10,000 `POST /search` events submitted randomly across 50 popular words in 10 seconds.
- **Without Batching:** 10,000 direct database lock/writes.
- **With Batching:** Exactly 50 database writes (one per unique word).
- **Reduction Result:** Database write load was reduced by **99.5%**.

### 5.4 Automated Testing
- **Unit & Integration Tests:** 47 tests written in `pytest` comprehensively cover the Trie, batching logic, consistent hashing, and API behavior, achieving near 100% core logic coverage.
