# Backend Image Tags

Backend (`main`): `ghcr.io/nekosuneprojects/nekosuneai:release-1.2.1`.
Pi Proxy (`build/pi-proxy-release`): `ghcr.io/nekosuneprojects/nekosuneai:piproxy-1.2.1`.

The backend workflow reads `VERSION` and publishes `release-<version>` after
amd64 and arm64 smoke tests. Pushes to `main` and manual dispatch on `main`
run the tests, update the existing Git `v<version>` tag and dispatch publishing.
Git release tags remain `v1.2.1`; container tags now use the product prefix.

Neither product publishes bare version, short version or `latest` image tags
through these workflows. Previously published tags are not deleted, but stop
receiving updates. Update external deployments pinned to `:1.2.1` to use
`:release-1.2.1`, then run `docker compose pull && docker compose up -d --no-build`
once the new image has actually been published.

Pi Proxy owns its separate Dockerfile and workflow. Do not merge its branch into
`main`. Both workflows use the existing self-hosted Linux X64 runner with Docker,
Buildx/QEMU support and GHCR package-write permission.

Tag generation follows [Docker metadata-action](https://github.com/docker/metadata-action)
with automatic `latest` disabled. Local configuration checks do not prove that
either architecture built or was published; verify the completed Actions runs.
