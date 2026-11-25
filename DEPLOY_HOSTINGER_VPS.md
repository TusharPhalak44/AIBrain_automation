# Hostinger VPS Production Deployment Guide (Docker + Nginx + MySQL 8.0)

This guide deploys the **XM Global MT5 Trading Portal V2** (`frontend`, `backend`, and `mysql:8.0`) onto a Hostinger KVM/VPS running **Ubuntu 22.04 / 24.04**.

---

## 1. Prerequisites on Hostinger VPS

SSH into your Hostinger VPS:
```bash
ssh root@YOUR_VPS_IP
```

Install Docker Engine & Docker Compose plugin:
```bash
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
docker compose version
```

Allow HTTP/HTTPS through UFW firewall (if enabled):
```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

---

## 2. Upload or Clone the Project

```bash
mkdir -p /opt/aibrain
cd /opt/aibrain
# Either git clone your repo here, or scp/rsync from your Windows machine:
# git clone <YOUR_REPO_URL> .
```

Create the Certbot directories referenced by `docker-compose.yml`:
```bash
mkdir -p /opt/aibrain/certbot/conf /opt/aibrain/certbot/www
```

---

## 3. Configure Production `.env`

Copy the production template:
```bash
cp .env.production.example .env
```

Generate a valid 32-byte Fernet `MASTER_ENCRYPTION_KEY`:
```bash
python3 -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```
*(Or using `cryptography`: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)*

Edit `.env` and fill in strong credentials:
```bash
nano .env
```
Required values:
- `MYSQL_PASSWORD` (strong password for `aibrain_user`)
- `MYSQL_ROOT_PASSWORD` (strong root password)
- `MASTER_ENCRYPTION_KEY` (the generated Fernet key from above)

---

## 4. Build and Launch the Stack

```bash
cd /opt/aibrain
docker compose up -d --build
```

Verify all 3 containers (`aibrain_mysql`, `aibrain_backend`, `aibrain_nginx`) are healthy:
```bash
docker compose ps
docker compose logs -f backend
```

Once `aibrain_backend` logs `Initialized database schema and seeded default records.`, open your browser to:
```
http://YOUR_VPS_IP/
```
Health endpoint check:
```bash
curl -s http://127.0.0.1/api/health
```

---

## 5. (Optional) Migrate Your Local XAMPP MySQL Data to VPS

If you want to carry over your existing `learned_pair_rules`, `trade_ledger`, `saved_strategies`, and settings from Windows XAMPP:

1. **On Windows (PowerShell):**
   ```powershell
   C:\xampp\mysql\bin\mysqldump.exe -u root xm_trading_v2 > xm_trading_v2_backup.sql
   ```
2. **Upload to VPS:**
   ```powershell
   scp xm_trading_v2_backup.sql root@YOUR_VPS_IP:/opt/aibrain/
   ```
3. **Import into Docker MySQL on VPS:**
   ```bash
   cd /opt/aibrain
   source .env
   docker exec -i aibrain_mysql mysql -u root -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" < xm_trading_v2_backup.sql
   docker compose restart backend
   ```
   > **Note:** If migrating encrypted secrets (Gemini API key, Telegram token), make sure `.env` on the VPS uses the **same** `MASTER_ENCRYPTION_KEY` as your local `.env`, or simply re-enter those keys in the UI Settings modal.

---

## 6. (Optional) Enable Free HTTPS / SSL with Domain & Certbot

1. Point your domain's `A` record to `YOUR_VPS_IP` in Hostinger DNS Zone.
2. Issue the SSL certificate using Certbot webroot:
   ```bash
   docker run --rm \
     -v /opt/aibrain/certbot/conf:/etc/letsencrypt \
     -v /opt/aibrain/certbot/www:/var/www/certbot \
     certbot/certbot certonly --webroot \
     -w /var/www/certbot -d your-domain.com --email you@example.com --agree-tos --no-eff-email
   ```
3. Uncomment the `443 ssl` server block in `nginx/nginx.conf`, replace `your-domain.com`, and rebuild Nginx:
   ```bash
   docker compose up -d --build nginx
   ```

---

## 7. Note on MetaTrader 5 (MT5) Terminal

- `MetaTrader5` Python IPC is Windows-only (`sys_platform == 'win32'`). On a Linux VPS, `backend` automatically runs cleanly with `mt5_bridge` on standby (all AI Brain, Strategy Lab, Backtester, Rules Vault, MySQL, and Telegram services run normally).
- For live MT5 order execution, connect your MT5 terminal on a Windows host/VPS or configure the remote MySQL sync from your Windows MT5 terminal to this VPS MySQL instance.

---

## 8. Common Operations

- **View logs:** `docker compose logs -f --tail=100`
- **Restart after code pull:** `git pull && docker compose up -d --build`
- **Backup MySQL database:**
  ```bash
  source .env && docker exec aibrain_mysql mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" > backup_$(date +%F).sql
  ```

