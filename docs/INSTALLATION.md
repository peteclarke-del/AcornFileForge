# Installing Acorn File Forge

Acorn File Forge is distributed as a Docker application. The same repository builds on 64-bit desktop Linux, Apple Silicon through Docker Desktop, x86-64 systems and Raspberry Pi Linux. CI builds `linux/amd64`, `linux/arm64` and 32-bit `linux/arm/v7` on every pull request.

## Desktop installation

Install Git, Docker Engine and Docker Compose, then use the public HTTPS address:

```bash
git clone https://github.com/peteclarke-del/AcornFileForge.git
cd AcornFileForge
docker compose up --build -d
```

Open <http://localhost:8666>. Port `8668` carries the managed emulator display. Do not expose either port to an untrusted network without putting an authenticated reverse proxy in front of them.

The first build compiles the bundled disk conversion and emulator tools. Later builds reuse Docker's layer cache. View build output with `docker compose build --progress=plain` if a slow machine appears idle.

## Raspberry Pi installation

A 64-bit Raspberry Pi OS installation is recommended, although current 32-bit Raspberry Pi OS releases are also covered by the build matrix. Make sure the root filesystem has several gigabytes free for compiler layers, the final application image and working media.

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Log out and back in after changing group membership. Then clone and build as the normal user:

```bash
git clone https://github.com/peteclarke-del/AcornFileForge.git
cd AcornFileForge
docker compose build --pull --progress=plain
docker compose up -d
```

Open `http://<pi-address>:8666` from a browser on the same trusted network. The multi-stage Dockerfile compiles Capstone when the architecture does not have a suitable binary package. It installs the resulting native module into a staged Python tree so the runtime does not repeat wheel-tag compatibility checks after a successful native build. It also compiles HxC, Elkulator and B-em. A first Pi build can therefore take a while, but it must keep producing build output. The compiler and headers remain in builder layers and are not copied into the runtime image.

## Updates and retained work

```bash
git pull --ff-only
docker compose build
docker compose up -d
```

The named `acorn-file-forge-work` volume retains browser-owned working sessions across container replacement. `docker compose down` leaves it intact. `docker compose down -v` deletes it and must only be used when every retained session can be discarded.

## Checks

```bash
docker compose ps
curl http://localhost:8666/api/health
docker compose logs --tail=100 acorn-file-forge
```

A healthy API response contains `{"engine":"oaknut","status":"ok","version":"1.0.0-rc.1"}`. If the browser page is stale after an update, refresh it once. Open panes are restored from browser-local workspace state and the server-side session remains tied to that browser identity.

## Common installation mistakes

- `git@github.com: Permission denied (publickey)` means SSH credentials are not configured. Use the HTTPS clone command above.
- `no configuration file provided` usually means the shell is not inside the cloned `AcornFileForge` directory.
- A historic `make: command not found` while building Capstone means an old Dockerfile is being used. Pull the current branch and rebuild.
- `Package liballegro4.4 has no installation candidate` means the checkout predates the Debian Trixie package-name correction. Pull the current branch and rebuild with `--pull`.
- `No matching distribution found for capstone` after a successful wheel build means the checkout still transports architecture-tagged wheels between build stages. Pull the current branch and rebuild; the current image copies a verified staged installation instead.
- An out-of-memory failure on a small Pi is a host resource problem. Stop unrelated containers, enable sensible swap and rebuild with plain progress output.
