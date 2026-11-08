## HTTP server benchmark

Compares:

| Program | Server | `/api` behaviour |
|---------|--------|------------------|
| `src/http_srv.te` | blocking `http.srv` **:8765** | `tim.wait(100)` **on the server thread** before responding |
| `src/nhttp_srv.te` | non-blocking `nhttp.asrv` **:8766** | `~~ slow_job()` (100 ms on a **worker**); response returns immediately (`queued`) |

Client: `src/bench.te` — parallel waves of concurrent `http.get` via `~~` + `async.drain`.

### OS / compiler requirements

```text
Python 3.12+
gcc or clang (C11)
pthread          — linked automatically (-lpthread)
OpenSSL          — libssl-dev / openssl (HTTPS client; optional for this bench)
```

**Linux process limits** (needed for high concurrency client or server):

```bash
# Allow enough open sockets (client opens many short connections)
ulimit -n 65535

# Optional: more user processes/threads if you raise conc a lot
ulimit -u 65535
```

**Kernel / soft limits** that often bite under load:

| Setting | Why |
|---------|-----|
| `ulimit -n` (nofile) | Each in-flight client + server fd needs a slot |
| ephemeral port range | Many short `connect()`s can exhaust local ports; wait for `TIME_WAIT` or raise range |
| `TERSE_ASYNC_MAX` (runtime, default 2048) | Max tracked `~~` client tasks; finished tasks are reaped |
| `SOCK_NB_MAX` (runtime, default 256) | Max concurrent connections in `nhttp` select loop |

Build with force so runtime changes pick up:

```bash
python3 compiler/tersec.py build src/http_srv.te  -o out/http_srv  -f
python3 compiler/tersec.py build src/nhttp_srv.te -o out/nhttp_srv -f
python3 compiler/tersec.py build src/bench.te     -o out/bench     -f
```

### Run

```bash
./out/http_srv &          # :8765
./out/nhttp_srv &         # :8766

./out/bench
# same as: n=1000 conc=50 against both /api endpoints

# Or explicit:
./out/bench par http://127.0.0.1:8766/api 1000 50
./out/bench par http://127.0.0.1:8765/api 1000 50
```

### Results (`./out/bench`, n=1000, conc=50)

| Server | completed | ms | req/s≈ |
|--------|----------:|---:|-------:|
| **nhttp** `:8766/api` (`~~` background work) | 1000 | **344** | **~2906** |
| **blocking** `:8765/api` (in-request sleep) | 1000 | **103163** | **~9** |

Roughly **300×** higher throughput for nhttp under the same concurrent client load.

Interpretation:

- Blocking: each `/api` holds the only server thread for ~100 ms → ceiling ≈ 10 req/s (measured ~9).
- nhttp: handler returns at once; 100 ms work runs on worker threads; select keeps accepting → measured ~2900 req/s (limited by client connect/HTTP overhead, not the sleep).

### Why this shows nhttp’s advantage

| | Blocking | nhttp (this setup) |
|--|----------|---------------------|
| `/api` path | Sleep **then** respond | Respond **now**; sleep on `~~` worker |
| Concurrent clients | Queue behind 100 ms slots | Handled as fast as accept/respond allows |
| Best for | Low traffic, simple demos | Many concurrent users / slow side work |

**Note:** Response bodies differ slightly (`{"ok":true}` vs `{"ok":true,"queued":true}`). The point is multi-user **capacity**, not identical semantics. True “wait 100 ms then send body” without blocking other clients needs event-loop timers (not only pthread join on the select thread).

### ApacheBench (optional)

```bash
ab -n 2000 -c 60 http://127.0.0.1:8765/api | tee benchmark/blocking.txt
ab -n 2000 -c 60 http://127.0.0.1:8766/api | tee benchmark/nonblocking.txt
```

Earlier ab runs with **both** handlers sleeping on the serve thread looked similar (~80 rps). That is expected: blocking work on the event-loop thread cancels non-blocking benefits. The `src/bench.te` scenario above is the fair multi-user comparison.

### Sockets and memory

| | `http.srv` | `nhttp.asrv` |
|--|------------|--------------|
| Active client sockets | **1** | **1…256** (`SOCK_NB_MAX`) |
| Peak I/O memory | One connection | Up to 256 × ~16 KiB buffers + state |

nhttp uses **more** peak sockets/RAM under concurrency on purpose. vs **thread-per-connection**, it still uses far less memory (no large stack per client).

### Which to use for many web clients?

**Prefer `nhttp.asrv`** when many clients overlap. Use blocking `http.srv` for demos and single-client tools.
