from pathlib import Path

import yaml


def test_proxy_tags_and_build_are_product_scoped():
    workflow = yaml.safe_load(Path(".github/workflows/pi-proxy-image.yml").read_text("utf-8"))
    jobs = workflow["jobs"]
    assert jobs["publish"]["needs"] == "smoke"
    assert jobs["smoke"]["strategy"]["matrix"]["arch"] == ["amd64", "arm64"]
    assert all(job["if"] == "github.ref == 'refs/heads/build/pi-proxy-release'" for job in jobs.values())
    metadata = next(s["with"] for s in jobs["publish"]["steps"] if s.get("id") == "meta")
    assert metadata["flavor"] == "latest=false"
    assert metadata["tags"] == "type=raw,value=piproxy-${{ steps.version.outputs.version }}"
    compose = yaml.safe_load(Path("compose.pi-proxy.yml").read_text("utf-8"))["services"]["pi-proxy"]
    version = Path("VERSION").read_text().strip()
    assert compose["image"] == f"ghcr.io/nekosuneprojects/nekosuneai:piproxy-{version}"
    assert compose["build"]["dockerfile"] == "Dockerfile.pi-proxy"
    dockerfile = Path("Dockerfile.pi-proxy").read_text()
    assert "-r requirements-pi-proxy.txt" in dockerfile
    assert "-r requirements.txt" not in dockerfile
    assert 'ENTRYPOINT ["python", "-m", "nekosuneai.pi_proxy_agent"]' in dockerfile
    assert Path("Dockerfile.pi-proxy.dockerignore").read_text().startswith("**\n")
