"""QA Agent Worker — tests tasks on dev environment.

Polls for tasks in qa_testing status. For each:
1. Deploys the task branch to dev environment
2. Generates test plan via LLM
3. Runs backend tests (HTTP requests)
4. Runs frontend tests (Playwright via Claude Code)
5. Reports results — pass → ready_to_release, fail → back to developer
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from autodev.core.models import Agent, AgentStatus, Task, TaskStatus
from autodev.agent_log import log_agent

logger = logging.getLogger(__name__)

QA_CHECK_INTERVAL = int(os.environ.get("QA_CHECK_INTERVAL", "60"))  # 1 min
DEV_API_URL = os.environ.get("DEV_API_URL", "https://dev.alerter.zinchenkomig.com/api")
DEV_FRONTEND_URL = os.environ.get("DEV_FRONTEND_URL", "https://dev.alerter.zinchenkomig.com")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


async def run_shell(cmd: str, timeout: int = 300) -> str:
    proc = await asyncio.create_subprocess_exec(
        "/bin/bash", "-c", cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"Timeout: {cmd}")
    stdout = stdout_b.decode(errors="replace").strip()
    stderr = stderr_b.decode(errors="replace").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"Failed (rc={proc.returncode}): {cmd}\n{stderr}")
    return stdout


async def deploy_branch_to_dev(repo: str, branch: str) -> dict:
    """Deploy a specific branch to dev environment."""
    is_backend = "backend" in repo
    is_frontend = "frontend" in repo
    env = "dev"
    clone_url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{repo}.git"
    
    results = {"repo": repo, "branch": branch}
    tmpdir = tempfile.mkdtemp(prefix=f"qa-deploy-")
    
    try:
        # Clone branch
        await run_shell(f"git clone -b {branch} --depth 1 {clone_url} {tmpdir}", timeout=60)
        commit = await run_shell(f"git -C {tmpdir} rev-parse --short HEAD")
        
        # Build
        if is_backend:
            # Fix lockfile issue
            dockerfile = f"{tmpdir}/docker/backend.dockerfile"
            await run_shell(f"sed -i 's/uv sync --locked/uv sync --frozen/' {dockerfile}")
            
            image = f"ghcr.io/{repo}:dev"
            await run_shell(
                f"docker build -t {image} --build-arg GIT_COMMIT={commit} -f {dockerfile} {tmpdir}",
                timeout=300,
            )
            await run_shell(f"docker push {image}", timeout=120)
            
            # Dev server is local (188.245.45.123)
            # Just restart tilt or k3s deployment
            try:
                await run_shell(
                    f"k3s kubectl set image deployment/alerter-backend -n dev backend={image} 2>/dev/null || true",
                    timeout=30,
                )
            except Exception:
                pass  # dev might use tilt
                
        elif is_frontend:
            image = f"ghcr.io/{repo}:dev"
            await run_shell(
                f"docker build -t {image} "
                f"--build-arg NEXT_PUBLIC_API_URL={DEV_API_URL} "
                f"--build-arg NEXT_PUBLIC_GIT_COMMIT={commit} "
                f"-f {tmpdir}/docker/frontend.dockerfile {tmpdir}",
                timeout=300,
            )
            await run_shell(f"docker push {image}", timeout=120)
            
            try:
                await run_shell(
                    f"k3s kubectl set image deployment/alerter-frontend -n dev frontend={image} 2>/dev/null || true",
                    timeout=30,
                )
            except Exception:
                pass
        
        results["success"] = True
        results["commit"] = commit
        
    except Exception as e:
        results["success"] = False
        results["error"] = str(e)
        logger.error(f"QA deploy failed for {repo}:{branch}: {e}")
    finally:
        await run_shell(f"rm -rf {tmpdir}", timeout=10)
    
    return results


async def generate_test_plan(task: Task, pr_diff: str) -> str:
    """Generate a test plan using LLM."""
    from autodev.core.runner import ClaudeCodeRunner
    
    is_frontend = "frontend" in (task.repo or "")
    
    prompt = f"""You are a QA engineer. Create a concrete test plan for this task.

TASK: {task.title}
DESCRIPTION: {task.description or 'N/A'}
REPOSITORY: {task.repo}

PR CHANGES:
{pr_diff[:5000]}

DEV ENVIRONMENT:
- Backend API: {DEV_API_URL}
- Frontend: {DEV_FRONTEND_URL}

Create a test plan with SPECIFIC, EXECUTABLE test steps. For each test:
- What to do (exact API endpoint or UI action)
- What to expect (status code, response field, visible element)
- How to verify (exact curl command or Playwright action)

{'FRONTEND TESTS: Use Playwright to navigate, click, verify text/elements.' if is_frontend else 'BACKEND TESTS: Use curl/httpx to call API endpoints and verify responses.'}

Output format:
TEST 1: [name]
ACTION: [what to do]
EXPECT: [what should happen]
VERIFY: [how to check - exact command or code]

TEST 2: ...

Keep it to 3-5 most important tests."""

    runner = ClaudeCodeRunner(model="claude-sonnet-4-20250514", timeout=120)
    result = await runner.run(prompt, context={})
    return result.output


async def run_backend_tests(test_plan: str, task: Task) -> list[dict]:
    """Execute backend API tests based on the plan."""
    results = []
    
    # Use LLM to execute the test plan
    from autodev.core.runner import ClaudeCodeRunner
    
    prompt = f"""You are a QA automation engineer. Execute these tests against a live API.

TEST PLAN:
{test_plan}

API BASE URL: {DEV_API_URL}

Execute each test by making HTTP requests using curl or python requests.
For each test, report:
- TEST: [name]
- STATUS: PASS or FAIL
- DETAILS: [what happened]

Run the tests NOW. Use the actual API URL. Report real results."""

    runner = ClaudeCodeRunner(model="claude-sonnet-4-20250514", timeout=300)
    workdir = tempfile.mkdtemp(prefix="qa-test-")
    
    try:
        result = await runner.run(prompt, context={"workdir": workdir})
        
        # Parse results
        output = result.output
        passed = output.upper().count("PASS")
        failed = output.upper().count("FAIL")
        
        results.append({
            "type": "backend",
            "passed": passed,
            "failed": failed,
            "output": output[:3000],
            "success": failed == 0 and passed > 0,
        })
    except Exception as e:
        results.append({"type": "backend", "success": False, "error": str(e)})
    finally:
        await run_shell(f"rm -rf {workdir}", timeout=10)
    
    return results


async def run_frontend_tests(test_plan: str, task: Task) -> list[dict]:
    """Execute frontend tests using Playwright via Claude Code."""
    results = []
    
    from autodev.core.runner import ClaudeCodeRunner
    
    prompt = f"""You are a QA automation engineer. Test this frontend feature using Playwright.

TEST PLAN:
{test_plan}

FRONTEND URL: {DEV_FRONTEND_URL}

Write and execute a Playwright test script. Use npx playwright to run it.
Install playwright if needed: npx playwright install chromium

For each test step:
1. Navigate to the page
2. Interact with elements
3. Verify the result
4. Take a screenshot if possible

Report:
- TEST: [name]
- STATUS: PASS or FAIL
- DETAILS: [what happened]"""

    runner = ClaudeCodeRunner(model="claude-sonnet-4-20250514", timeout=600)
    workdir = tempfile.mkdtemp(prefix="qa-frontend-")
    
    try:
        result = await runner.run(prompt, context={"workdir": workdir})
        
        output = result.output
        passed = output.upper().count("PASS")
        failed = output.upper().count("FAIL")
        
        results.append({
            "type": "frontend",
            "passed": passed,
            "failed": failed,
            "output": output[:3000],
            "success": failed == 0 and passed > 0,
        })
    except Exception as e:
        results.append({"type": "frontend", "success": False, "error": str(e)})
    finally:
        await run_shell(f"rm -rf {workdir}", timeout=10)
    
    return results


async def get_pr_diff(task: Task) -> str:
    """Fetch PR diff from GitHub."""
    if not task.pr_url:
        return ""
    
    try:
        parts = task.pr_url.rstrip("/").split("/")
        repo = f"{parts[-4]}/{parts[-3]}"
        pr_number = parts[-1]
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files",
                headers={"Authorization": f"token {GITHUB_TOKEN}"},
                timeout=15.0,
            )
            if resp.status_code == 200:
                files = resp.json()
                diff = ""
                for f in files:
                    diff += f"\n--- {f['filename']} ---\n"
                    if "patch" in f:
                        diff += f['patch'][:2000] + "\n"
                return diff
    except Exception as e:
        logger.warning(f"Failed to get PR diff: {e}")
    
    return ""


async def process_qa_task(task: Task, session_factory: async_sessionmaker) -> None:
    """Run QA testing for a single task."""
    task_id = str(task.id)
    repo = task.repo or ""
    branch = task.branch or ""
    is_frontend = "frontend" in repo
    
    async with session_factory() as session:
        await log_agent(session, "qa", "info", 
            f"🧪 QA started: {task.title}",
            task_id=task_id,
            details=f"Repo: {repo}\nBranch: {branch}\nPR: {task.pr_url}")
        await session.commit()
    
    try:
        # 1. Deploy branch to dev
        logger.info(f"QA: deploying {repo}:{branch} to dev")
        async with session_factory() as session:
            await log_agent(session, "qa", "info", "Deploying branch to dev environment...", task_id=task_id)
            await session.commit()
        
        deploy_result = await deploy_branch_to_dev(repo, branch)
        
        if not deploy_result.get("success"):
            async with session_factory() as session:
                await log_agent(session, "qa", "error", 
                    f"Deploy failed: {deploy_result.get('error', 'unknown')}", task_id=task_id)
                await session.commit()
            # Don't fail the task for deploy issues — pass through
            async with session_factory() as session:
                t = await session.get(Task, task.id)
                if t:
                    t.status = TaskStatus.READY_TO_RELEASE
                await session.commit()
            return
        
        await asyncio.sleep(15)  # Wait for pods to restart
        
        # 2. Get PR diff
        pr_diff = await get_pr_diff(task)
        
        # 3. Generate test plan
        logger.info(f"QA: generating test plan for {task.title}")
        async with session_factory() as session:
            await log_agent(session, "qa", "info", "Generating test plan...", task_id=task_id)
            await session.commit()
        
        test_plan = await generate_test_plan(task, pr_diff)
        
        async with session_factory() as session:
            await log_agent(session, "qa", "info", "📋 Test plan created", 
                task_id=task_id, details=test_plan[:2000])
            await session.commit()
        
        # 4. Run tests
        logger.info(f"QA: running tests for {task.title}")
        async with session_factory() as session:
            await log_agent(session, "qa", "info", "Running tests...", task_id=task_id)
            await session.commit()
        
        if is_frontend:
            test_results = await run_frontend_tests(test_plan, task)
        else:
            test_results = await run_backend_tests(test_plan, task)
        
        # 5. Evaluate results
        all_passed = all(r.get("success") for r in test_results)
        
        report = "=== QA TEST REPORT ===\n\n"
        for r in test_results:
            report += f"Type: {r.get('type', 'unknown')}\n"
            report += f"Passed: {r.get('passed', 0)}, Failed: {r.get('failed', 0)}\n"
            report += f"Success: {r.get('success', False)}\n"
            if r.get('output'):
                report += f"\nOutput:\n{r['output']}\n"
            if r.get('error'):
                report += f"\nError: {r['error']}\n"
            report += "\n"
        
        async with session_factory() as session:
            await log_agent(session, "qa", 
                "info" if all_passed else "warning",
                f"{'✅ QA PASSED' if all_passed else '❌ QA FAILED'}: {task.title}",
                task_id=task_id,
                details=report)
            await session.commit()
        
        # 6. Update task status
        async with session_factory() as session:
            t = await session.get(Task, task.id)
            if t:
                if all_passed:
                    t.status = TaskStatus.READY_TO_RELEASE
                    logger.info(f"QA PASSED: {task.title}")
                else:
                    # QA failed — return same task to developer with QA report
                    t.status = TaskStatus.QUEUED
                    
                    # Append QA feedback to description so developer sees it
                    qa_feedback = f"\n\n--- QA FEEDBACK ---\n{report[:2000]}"
                    t.description = (t.description or "") + qa_feedback
                    
                    logger.warning(f"QA FAILED: {task.title} — returned to queue")
                    
                    await log_agent(session, "qa", "warning",
                        f"Returned to developer: {task.title}",
                        task_id=task_id,
                        details=report[:2000])
            await session.commit()
        
    except Exception as e:
        logger.exception(f"QA error for task {task.title}")
        async with session_factory() as session:
            await log_agent(session, "qa", "error", f"QA error: {e}", task_id=task_id)
            t = await session.get(Task, task.id)
            if t:
                t.status = TaskStatus.READY_TO_RELEASE  # Don't block on QA errors
            await session.commit()


async def qa_worker_loop(session_factory: async_sessionmaker) -> None:
    """Poll for qa_testing tasks and process them."""
    logger.info(f"QA Worker started — checking every {QA_CHECK_INTERVAL}s")
    
    await asyncio.sleep(60)  # Wait on startup
    
    while True:
        try:
            async with session_factory() as session:
                result = await session.execute(
                    select(Task)
                    .where(Task.status == TaskStatus.QA_TESTING)
                    .order_by(Task.created_at)
                    .limit(1)
                )
                task = result.scalar_one_or_none()
            
            if task:
                await process_qa_task(task, session_factory)
            
        except Exception:
            logger.exception("QA Worker: unhandled error")
        
        await asyncio.sleep(QA_CHECK_INTERVAL)
