"""Deploy to staging or production.

Builds from stage branch (staging) or main (production),
pushes Docker images, and restarts k8s deployments.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

REMOTE = "root@178.104.35.218"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
STAGING_BRANCH = "stage"


async def run_shell(cmd: str, timeout: int = 300) -> str:
    """Run shell command and return stdout."""
    proc = await asyncio.create_subprocess_exec(
        "/bin/bash",
        "-c",
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"Command timed out: {cmd}")

    stdout = stdout_b.decode(errors="replace").strip()
    stderr = stderr_b.decode(errors="replace").strip()

    if proc.returncode != 0:
        raise RuntimeError(f"Command failed (rc={proc.returncode}): {cmd}\nstderr: {stderr}")

    return stdout


async def get_stage_commit(repo: str) -> str:
    """Get the current commit hash of the stage branch. Returns short hash."""
    clone_url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{repo}.git"
    tmpdir = tempfile.mkdtemp(prefix=f"stage-{repo.split('/')[-1]}-")

    try:
        await run_shell(f"git clone -b {STAGING_BRANCH} {clone_url} {tmpdir}", timeout=120)
        commit = await run_shell(f"git -C {tmpdir} rev-parse --short HEAD")
        logger.info(f"{repo} {STAGING_BRANCH} branch at {commit}")
        return commit
    finally:
        await run_shell(f"rm -rf {tmpdir}", timeout=10)


async def deploy_staging(repos: list[str] | None = None, release_version: str = "") -> dict:
    """Deploy stage branch to staging.

    Args:
        repos: List of repos to deploy. None = all.
        release_version: Release version string to display on frontend.

    Returns:
        Dict with deploy results per repo.
    """
    if repos is None:
        repos = ["zinchenkomig/great_alerter_backend", "zinchenkomig/great_alerter_frontend"]

    results = {}

    for repo in repos:
        repo_name = repo.split("/")[-1]
        is_backend = "backend" in repo_name
        is_frontend = "frontend" in repo_name
        env = "staging"
        branch = STAGING_BRANCH

        clone_url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{repo}.git"

        # PRs are merged directly into stage, so just deploy from it
        logger.info(f"Deploying {repo_name} to {env} from {branch}")

        try:
            tmpdir = tempfile.mkdtemp(prefix=f"deploy-{repo_name}-")

            # Clone
            await run_shell(f"git clone -b {branch} {clone_url} {tmpdir}", timeout=120)

            # Get commit
            commit = await run_shell(f"git -C {tmpdir} rev-parse --short HEAD")

            # Build
            if is_backend:
                dockerfile = "docker/backend.dockerfile"
            elif is_frontend:
                api_url = "https://staging.alerter.zinchenkomig.com/api"
                dockerfile = "docker/frontend.dockerfile"
            else:
                continue

            image = f"ghcr.io/{repo}:{env}"

            build_args = f"--build-arg GIT_COMMIT={commit}"
            if is_frontend:
                build_args += f" --build-arg NEXT_PUBLIC_API_URL={api_url} --build-arg NEXT_PUBLIC_GIT_COMMIT={commit}"
                if release_version:
                    build_args += f" --build-arg NEXT_PUBLIC_RELEASE_VERSION={release_version}"

            logger.info(f"Building {image}...")
            await run_shell(
                f"docker build -t {image} {build_args} -f {tmpdir}/{dockerfile} {tmpdir}",
                timeout=300,
            )

            # Push
            logger.info(f"Pushing {image}...")
            await run_shell(f"docker push {image}", timeout=120)

            # Rollout on remote
            logger.info(f"Rolling out on {REMOTE}...")
            if is_backend:
                version_cmd = ""
                if release_version:
                    version_cmd = (
                        f"kubectl set env deployment/alerter-backend -n {env} RELEASE_VERSION={release_version} && "
                        f"kubectl set env deployment/alerter-backend-scheduler -n {env} RELEASE_VERSION={release_version} && "
                    )
                await run_shell(
                    f"ssh -o StrictHostKeyChecking=accept-new {REMOTE} "
                    f'"export KUBECONFIG=/etc/rancher/k3s/k3s.yaml && '
                    f"{version_cmd}"
                    f'kubectl rollout restart deployment/alerter-backend deployment/alerter-backend-scheduler -n {env}"',
                    timeout=60,
                )
                # Run migrations
                await asyncio.sleep(15)
                try:
                    await run_shell(
                        f"ssh {REMOTE} "
                        f'"export KUBECONFIG=/etc/rancher/k3s/k3s.yaml && '
                        f"BACKEND_POD=\\$(kubectl get pods -n {env} -l app.kubernetes.io/name=backend "
                        f"--field-selector=status.phase=Running -o jsonpath='{{.items[0].metadata.name}}') && "
                        f'kubectl exec -n {env} \\$BACKEND_POD -- alembic upgrade head"',
                        timeout=60,
                    )
                except Exception as e:
                    logger.warning(f"Migration failed (may be ok): {e}")

            elif is_frontend:
                # Set release version env var and rollout
                version_cmd = ""
                if release_version:
                    version_cmd = f"kubectl set env deployment/alerter-frontend -n {env} NEXT_PUBLIC_RELEASE_VERSION={release_version} && "
                await run_shell(
                    f"ssh -o StrictHostKeyChecking=accept-new {REMOTE} "
                    f'"export KUBECONFIG=/etc/rancher/k3s/k3s.yaml && '
                    f"{version_cmd}"
                    f'kubectl rollout restart deployment/alerter-frontend -n {env}"',
                    timeout=60,
                )

            # Cleanup
            await run_shell(f"rm -rf {tmpdir}")

            results[repo_name] = {"success": True, "commit": commit, "image": image}
            logger.info(f"✅ {repo_name} deployed to {env} ({commit})")

        except Exception as e:
            logger.error(f"❌ {repo_name} deploy failed: {e}")
            results[repo_name] = {"success": False, "error": str(e)}
            try:
                await run_shell(f"rm -rf {tmpdir}")
            except Exception:
                pass

    return results


async def deploy_production(repos: list[str] | None = None, release_version: str = "") -> dict:
    """Deploy main branch to production.

    Args:
        repos: List of repos to deploy. None = all.
        release_version: Release version string.

    Returns:
        Dict with deploy results per repo.
    """
    if repos is None:
        repos = ["zinchenkomig/great_alerter_backend", "zinchenkomig/great_alerter_frontend"]

    results = {}

    for repo in repos:
        repo_name = repo.split("/")[-1]
        is_backend = "backend" in repo_name
        is_frontend = "frontend" in repo_name
        env = "production"
        branch = "main"

        clone_url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{repo}.git"

        logger.info(f"Deploying {repo_name} to {env} from {branch}")

        try:
            tmpdir = tempfile.mkdtemp(prefix=f"deploy-{repo_name}-")

            # Clone
            await run_shell(f"git clone -b {branch} {clone_url} {tmpdir}", timeout=120)

            # Get commit
            commit = await run_shell(f"git -C {tmpdir} rev-parse --short HEAD")

            # Build
            if is_backend:
                dockerfile = "docker/backend.dockerfile"
            elif is_frontend:
                api_url = "https://alerter.zinchenkomig.com/api"
                dockerfile = "docker/frontend.dockerfile"
            else:
                continue

            image = f"ghcr.io/{repo}:{env}"

            build_args = f"--build-arg GIT_COMMIT={commit}"
            if is_frontend:
                build_args += f" --build-arg NEXT_PUBLIC_API_URL={api_url} --build-arg NEXT_PUBLIC_GIT_COMMIT={commit}"
                if release_version:
                    build_args += f" --build-arg NEXT_PUBLIC_RELEASE_VERSION={release_version}"

            logger.info(f"Building {image}...")
            await run_shell(
                f"docker build -t {image} {build_args} -f {tmpdir}/{dockerfile} {tmpdir}",
                timeout=300,
            )

            # Push
            logger.info(f"Pushing {image}...")
            await run_shell(f"docker push {image}", timeout=120)

            # Rollout on remote
            logger.info(f"Rolling out on {REMOTE}...")
            if is_backend:
                version_cmd = ""
                if release_version:
                    version_cmd = (
                        f"kubectl set env deployment/alerter-backend -n {env} RELEASE_VERSION={release_version} && "
                        f"kubectl set env deployment/alerter-backend-scheduler -n {env} RELEASE_VERSION={release_version} && "
                    )
                await run_shell(
                    f"ssh -o StrictHostKeyChecking=accept-new {REMOTE} "
                    f'"export KUBECONFIG=/etc/rancher/k3s/k3s.yaml && '
                    f"{version_cmd}"
                    f'kubectl rollout restart deployment/alerter-backend deployment/alerter-backend-scheduler -n {env}"',
                    timeout=60,
                )
                # Run migrations
                await asyncio.sleep(15)
                try:
                    await run_shell(
                        f"ssh {REMOTE} "
                        f'"export KUBECONFIG=/etc/rancher/k3s/k3s.yaml && '
                        f"BACKEND_POD=\\$(kubectl get pods -n {env} -l app.kubernetes.io/name=backend "
                        f"--field-selector=status.phase=Running -o jsonpath='{{.items[0].metadata.name}}') && "
                        f'kubectl exec -n {env} \\$BACKEND_POD -- alembic upgrade head"',
                        timeout=60,
                    )
                except Exception as e:
                    logger.warning(f"Production migration failed (may be ok): {e}")

            elif is_frontend:
                version_cmd = ""
                if release_version:
                    version_cmd = f"kubectl set env deployment/alerter-frontend -n {env} NEXT_PUBLIC_RELEASE_VERSION={release_version} && "
                await run_shell(
                    f"ssh -o StrictHostKeyChecking=accept-new {REMOTE} "
                    f'"export KUBECONFIG=/etc/rancher/k3s/k3s.yaml && '
                    f"{version_cmd}"
                    f'kubectl rollout restart deployment/alerter-frontend -n {env}"',
                    timeout=60,
                )

            # Cleanup
            await run_shell(f"rm -rf {tmpdir}")

            results[repo_name] = {"success": True, "commit": commit, "image": image}
            logger.info(f"✅ {repo_name} deployed to {env} ({commit})")

        except Exception as e:
            logger.error(f"❌ {repo_name} deploy failed: {e}")
            results[repo_name] = {"success": False, "error": str(e)}
            try:
                await run_shell(f"rm -rf {tmpdir}")
            except Exception:
                pass

    return results
