"""Latency benchmark measuring retrieval, E2E SQL tool, E2E doc tool, and TTFT SSE.

Runs a test uvicorn instance on an ephemeral port with the REAL embedding model,
evaluates p50/p95 latency and counts any 429 rate limit errors, and records hardware/model metadata.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

# Ephemeral port for benchmark server
BENCHMARK_PORT = 8011
BASE_URL = f"http://127.0.0.1:{BENCHMARK_PORT}"


def get_hardware_info() -> dict[str, Any]:
    info = {
        "os": platform.platform(),
        "python_version": platform.python_version(),
        "cpu": platform.processor() or "Unknown CPU",
        "cpu_count": os.cpu_count() or 1,
        "machine": platform.machine(),
    }
    try:
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        info["ram_total_gb"] = round(stat.ullTotalPhys / (1024**3), 2)
    except Exception:
        info["ram_total_gb"] = "N/A"
    return info


def calc_percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50_ms": 0.0, "p95_ms": 0.0, "mean_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0}
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    p50_idx = int(0.50 * (n - 1))
    p95_idx = int(0.95 * (n - 1))
    return {
        "p50_ms": round(sorted_vals[p50_idx] * 1000, 2),
        "p95_ms": round(sorted_vals[p95_idx] * 1000, 2),
        "mean_ms": round((sum(sorted_vals) / n) * 1000, 2),
        "min_ms": round(sorted_vals[0] * 1000, 2),
        "max_ms": round(sorted_vals[-1] * 1000, 2),
    }


async def run_scenario_retrieval(
    client: httpx.AsyncClient,
    token: str,
    total_requests: int = 20,
    concurrency: int = 3,
) -> dict[str, Any]:
    queries = [
        "How should amoxicillin be stored?",
        "What is the maximum heat for ibuprofen?",
        "Metformin contraindications eGFR threshold",
        "Omeprazole interaction with clopidogrel",
        "Lisinopril fetal toxicity warnings",
    ]
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    status_counts: dict[int, int] = {}
    errors: list[str] = []

    async def worker(idx: int):
        q = queries[idx % len(queries)]
        async with sem:
            t0 = time.perf_counter()
            try:
                resp = await client.get(
                    "/api/v1/documents/search",
                    params={"q": q, "k": 4},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=30.0,
                )
                dur = time.perf_counter() - t0
                status_counts[resp.status_code] = status_counts.get(resp.status_code, 0) + 1
                if resp.status_code == 200:
                    latencies.append(dur)
                else:
                    errors.append(f"Status {resp.status_code}: {resp.text[:100]}")
            except Exception as exc:
                errors.append(str(exc))

    tasks = [worker(i) for i in range(total_requests)]
    await asyncio.gather(*tasks)

    stats = calc_percentiles(latencies)
    return {
        "scenario": "Retrieval only (no LLM, real embeddings)",
        "endpoint": "GET /api/v1/documents/search",
        "total_requests": total_requests,
        "concurrency": concurrency,
        "successful_requests": len(latencies),
        "rate_limited_429": status_counts.get(429, 0),
        "status_distribution": status_counts,
        "errors": errors[:5],
        **stats,
    }


async def run_scenario_chat_sql(
    client: httpx.AsyncClient,
    token: str,
    total_requests: int = 10,
    concurrency: int = 2,
) -> dict[str, Any]:
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    status_counts: dict[int, int] = {}
    errors: list[str] = []

    async def worker(idx: int):
        async with sem:
            t0 = time.perf_counter()
            try:
                resp = await client.post(
                    "/api/v1/chat",
                    json={"query": "Which batches of amoxicillin expire in the next 60 days?"},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=60.0,
                )
                dur = time.perf_counter() - t0
                status_counts[resp.status_code] = status_counts.get(resp.status_code, 0) + 1
                if resp.status_code == 200:
                    latencies.append(dur)
                else:
                    errors.append(f"Status {resp.status_code}: {resp.text[:100]}")
            except Exception as exc:
                errors.append(str(exc))
            await asyncio.sleep(0.5)

    tasks = [worker(i) for i in range(total_requests)]
    await asyncio.gather(*tasks)

    stats = calc_percentiles(latencies)
    return {
        "scenario": "SQL tool E2E (agent + db query)",
        "endpoint": "POST /api/v1/chat (stock question)",
        "total_requests": total_requests,
        "concurrency": concurrency,
        "successful_requests": len(latencies),
        "rate_limited_429": status_counts.get(429, 0),
        "status_distribution": status_counts,
        "errors": errors[:5],
        **stats,
    }


async def run_scenario_chat_docs(
    client: httpx.AsyncClient,
    token: str,
    total_requests: int = 10,
    concurrency: int = 2,
) -> dict[str, Any]:
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    status_counts: dict[int, int] = {}
    errors: list[str] = []

    async def worker(idx: int):
        async with sem:
            t0 = time.perf_counter()
            try:
                resp = await client.post(
                    "/api/v1/chat",
                    json={"query": "What are the storage guidelines for metformin?"},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=60.0,
                )
                dur = time.perf_counter() - t0
                status_counts[resp.status_code] = status_counts.get(resp.status_code, 0) + 1
                if resp.status_code == 200:
                    latencies.append(dur)
                else:
                    errors.append(f"Status {resp.status_code}: {resp.text[:100]}")
            except Exception as exc:
                errors.append(str(exc))
            await asyncio.sleep(0.5)

    tasks = [worker(i) for i in range(total_requests)]
    await asyncio.gather(*tasks)

    stats = calc_percentiles(latencies)
    return {
        "scenario": "Doc-search E2E (agent + RAG guidelines)",
        "endpoint": "POST /api/v1/chat (guidelines question)",
        "total_requests": total_requests,
        "concurrency": concurrency,
        "successful_requests": len(latencies),
        "rate_limited_429": status_counts.get(429, 0),
        "status_distribution": status_counts,
        "errors": errors[:5],
        **stats,
    }


async def run_scenario_ttft_stream(
    client: httpx.AsyncClient,
    token: str,
    total_requests: int = 10,
    concurrency: int = 2,
) -> dict[str, Any]:
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    status_counts: dict[int, int] = {}
    errors: list[str] = []

    async def worker(idx: int):
        async with sem:
            t0 = time.perf_counter()
            first_token_time: float | None = None
            try:
                async with client.stream(
                    "POST",
                    "/api/v1/chat/stream",
                    json={"query": "How should ibuprofen be stored?"},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=60.0,
                ) as response:
                    status_counts[response.status_code] = status_counts.get(response.status_code, 0) + 1
                    if response.status_code == 200:
                        async for line in response.aiter_lines():
                            if line.startswith("event: token") or '"token"' in line:
                                first_token_time = time.perf_counter() - t0
                                break
                        if first_token_time is not None:
                            latencies.append(first_token_time)
                        else:
                            dur = time.perf_counter() - t0
                            latencies.append(dur)
                    else:
                        errors.append(f"Status {response.status_code}")
            except Exception as exc:
                errors.append(str(exc))
            await asyncio.sleep(0.5)

    tasks = [worker(i) for i in range(total_requests)]
    await asyncio.gather(*tasks)

    stats = calc_percentiles(latencies)
    return {
        "scenario": "TTFT (Server-Sent Events streaming)",
        "endpoint": "POST /api/v1/chat/stream",
        "total_requests": total_requests,
        "concurrency": concurrency,
        "successful_requests": len(latencies),
        "rate_limited_429": status_counts.get(429, 0),
        "status_distribution": status_counts,
        "errors": errors[:5],
        **stats,
    }


async def main_async() -> None:
    has_groq = bool(os.getenv("GROQ_API_KEY") and len(os.getenv("GROQ_API_KEY", "")) > 5)
    groq_model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    embedding_model = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    groq_tier = os.getenv("GROQ_TIER", "Developer / Free Tier (On-Demand)")

    hw = get_hardware_info()
    print("==================================================================")
    print("PHARMA AI AGENT LATENCY BENCHMARK")
    print(f"Platform: {hw['os']} ({hw['cpu']}, {hw['cpu_count']} cores, {hw['ram_total_gb']} GB RAM)")
    print(f"Embedding Model: {embedding_model} (REAL HuggingFace)")
    print(f"LLM Model: {groq_model} (Groq)")
    print(f"Groq Tier: {groq_tier}")
    print(f"Live Groq Key Configured: {has_groq}")
    print("==================================================================")

    # Launch uvicorn subprocess with real embeddings and disabled rate limits
    server_env = os.environ.copy()
    server_env["PORT"] = str(BENCHMARK_PORT)
    server_env["DB_HOST"] = "localhost"
    server_env["DB_PORT"] = "5432"
    server_env["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/pharma_test"
    server_env["EMBEDDINGS_BACKEND"] = "huggingface"
    server_env["RATE_LIMIT_ENABLED"] = "false"
    server_env["FAISS_INDEX_DIR"] = "data/faiss_bench"

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(BENCHMARK_PORT),
        "--log-level",
        "warning",
    ]
    proc = subprocess.Popen(cmd, env=server_env)
    print(f"Started benchmark API server (PID {proc.pid}) on http://127.0.0.1:{BENCHMARK_PORT}...")

    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            # Wait for health
            ready = False
            for _ in range(60):
                try:
                    r = await client.get("/health")
                    if r.status_code == 200:
                        ready = True
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.5)

            if not ready:
                raise RuntimeError("Benchmark server failed to start within 30 seconds.")
            print("Server is healthy and ready.")

            # Login to get JWT
            admin_user = os.getenv("ADMIN_USERNAME", "admin")
            admin_pass = os.getenv("ADMIN_PASSWORD", "admin-pass-123")
            login_resp = await client.post(
                "/api/v1/auth/login",
                json={"username": admin_user, "password": admin_pass},
            )
            if login_resp.status_code == 401:
                admin_pass = "admin-pass-123"
                login_resp = await client.post(
                    "/api/v1/auth/login",
                    json={"username": admin_user, "password": admin_pass},
                )
            if login_resp.status_code != 200:
                raise RuntimeError(f"Admin login failed: {login_resp.status_code} {login_resp.text}")
            token = login_resp.json()["access_token"]
            print("Successfully authenticated admin session.")

            results = {
                "metadata": {
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "hardware": hw,
                    "llm_model": groq_model,
                    "embedding_model": embedding_model,
                    "groq_tier": groq_tier,
                    "concurrency_notes": "Low concurrency (2-3 concurrent workers) with rate limit monitoring",
                },
                "scenarios": {},
            }

            # Scenario 1: Retrieval Only
            print("\nRunning Scenario 1: Retrieval Only (20 requests, concurrency=3)...")
            s1 = await run_scenario_retrieval(client, token, total_requests=20, concurrency=3)
            results["scenarios"]["retrieval_only"] = s1
            print(f"  -> p50: {s1['p50_ms']} ms | p95: {s1['p95_ms']} ms | 429 errors: {s1['rate_limited_429']}")

            if has_groq:
                # Scenario 2: SQL tool E2E
                print("\nRunning Scenario 2: SQL Tool E2E (10 requests, concurrency=2)...")
                s2 = await run_scenario_chat_sql(client, token, total_requests=10, concurrency=2)
                results["scenarios"]["sql_tool_e2e"] = s2
                print(f"  -> p50: {s2['p50_ms']} ms | p95: {s2['p95_ms']} ms | 429 errors: {s2['rate_limited_429']}")

                # Scenario 3: Doc search E2E
                print("\nRunning Scenario 3: Doc Search E2E (10 requests, concurrency=2)...")
                s3 = await run_scenario_chat_docs(client, token, total_requests=10, concurrency=2)
                results["scenarios"]["doc_search_e2e"] = s3
                print(f"  -> p50: {s3['p50_ms']} ms | p95: {s3['p95_ms']} ms | 429 errors: {s3['rate_limited_429']}")

                # Scenario 4: TTFT Stream
                print("\nRunning Scenario 4: TTFT SSE Stream (10 requests, concurrency=2)...")
                s4 = await run_scenario_ttft_stream(client, token, total_requests=10, concurrency=2)
                results["scenarios"]["ttft_sse_stream"] = s4
                print(f"  -> p50: {s4['p50_ms']} ms | p95: {s4['p95_ms']} ms | 429 errors: {s4['rate_limited_429']}")
            else:
                for k in ["sql_tool_e2e", "doc_search_e2e", "ttft_sse_stream"]:
                    results["scenarios"][k] = {"note": "N/A — GROQ_API_KEY not set"}

    finally:
        print("\nShutting down benchmark server...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    # Generate Markdown summary table
    table_lines = [
        "| Scenario | Endpoint | Requests | Concurrency | p50 (ms) | p95 (ms) | 429 Errors |",
        "|:---|:---|:---:|:---:|:---:|:---:|:---:|",
    ]
    for name, data in results["scenarios"].items():
        if "p50_ms" in data:
            table_lines.append(
                f"| **{data['scenario']}** | `{data['endpoint']}` | {data['total_requests']} | {data['concurrency']} | {data['p50_ms']} | {data['p95_ms']} | {data['rate_limited_429']} |"
            )
        else:
            table_lines.append(f"| **{name}** | N/A | N/A | N/A | N/A | N/A | N/A |")

    table_md = "\n".join(table_lines)
    print("\n### Benchmark Latency Results\n")
    print(table_md)
    print()

    # Save output artifacts
    root = Path(__file__).resolve().parent.parent
    docs_dir = root / "docs" / "evidence"
    docs_dir.mkdir(parents=True, exist_ok=True)

    json_path = docs_dir / "latency_results.json"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Saved JSON results to {json_path.relative_to(root)}")

    txt_path = docs_dir / "latency_results.txt"
    txt_content = (
        f"Benchmark Run: {results['metadata']['timestamp']}\n"
        f"Platform: {hw['os']} | CPU: {hw['cpu']} ({hw['cpu_count']} cores) | RAM: {hw['ram_total_gb']} GB\n"
        f"LLM Model: {groq_model} | Embedding Model: {embedding_model} | Groq Tier: {groq_tier}\n\n"
        f"{table_md}\n"
    )
    txt_path.write_text(txt_content, encoding="utf-8")
    print(f"Saved text results to {txt_path.relative_to(root)}")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
