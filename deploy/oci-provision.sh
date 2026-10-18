#!/usr/bin/env bash
# Provisionnement d'une instance Oracle Cloud Always Free (Oracle Linux 8/9 ou Ubuntu 22.04/24.04)
# Exécuté sur le serveur distant via : ssh <opc|ubuntu>@<IP> 'sudo bash -s' < deploy/oci-provision.sh
set -euo pipefail

echo "[1/7] Configuration du fuseau horaire Europe/Paris..."
timedatectl set-timezone Europe/Paris

echo "[2/7] Configuration du swap (2 Go si absent)..."
if ! swapon --show | grep -q '/swapfile'; then
    if [ ! -f /swapfile ]; then
        dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
        chmod 600 /swapfile
        mkswap /swapfile
    fi
    swapon /swapfile
    if ! grep -q '^/swapfile ' /etc/fstab; then
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
    fi
fi

echo "[3/7] Installation des paquets système (Caddy, Git, rsync, tar/unzip)..."
if command -v dnf >/dev/null 2>&1; then
    # Oracle Linux / RHEL 8 ou 9
    dnf install -y -q git rsync unzip tar curl ca-certificates policycoreutils-python-utils
    if ! command -v caddy >/dev/null 2>&1; then
        dnf install -y -q 'dnf-command(copr)' || true
        dnf copr enable -y @caddy/caddy || dnf install -y -q epel-release
        dnf install -y -q caddy
    fi
    systemctl enable --now caddy
elif command -v apt-get >/dev/null 2>&1; then
    # Ubuntu / Debian
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -q
    apt-get install -y -q ca-certificates curl gnupg git rsync unzip tar caddy iptables-persistent netfilter-persistent
else
    echo "Erreur : gestionnaire de paquets non reconnu (ni dnf ni apt-get)." >&2
    exit 1
fi

echo "[4/7] Ouverture des ports 80 et 443 dans le pare-feu local de l'instance..."
if systemctl is-active --quiet firewalld; then
    # Oracle Linux utilise firewalld par défaut
    firewall-cmd --permanent --add-service=http
    firewall-cmd --permanent --add-service=https
    firewall-cmd --reload
elif command -v netfilter-persistent >/dev/null 2>&1; then
    # Images Ubuntu sur Oracle Cloud
    for port in 80 443; do
        if ! iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null; then
            iptables -I INPUT 1 -p tcp --dport "$port" -m state --state NEW -j ACCEPT
        fi
        if command -v ip6tables >/dev/null 2>&1; then
            if ! ip6tables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null; then
                ip6tables -I INPUT 1 -p tcp --dport "$port" -m state --state NEW -j ACCEPT
            fi
        fi
    done
    netfilter-persistent save
fi

# Sur Oracle Linux (SELinux Enforcing), autoriser Caddy (httpd_t) à se connecter au port local 3820
if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce)" != "Disabled" ]; then
    setsebool -P httpd_can_network_connect 1 || true
fi

echo "[5/7] Création de l'utilisateur système 'pokeprice' et des dossiers isolés..."
if ! id -u pokeprice >/dev/null 2>&1; then
    useradd --system --user-group --home-dir /srv/pokeprice --no-create-home --shell /usr/sbin/nologin pokeprice
fi

install -d -m 0700 -o pokeprice -g pokeprice /srv/pokeprice
install -d -m 0700 -o pokeprice -g pokeprice /srv/pokeprice/inventory
install -d -m 0700 -o pokeprice -g pokeprice /srv/pokeprice/backups
install -d -m 0700 -o pokeprice -g pokeprice /srv/pokeprice/.config
install -d -m 0750 -o root -g pokeprice /etc/pokeprice
install -d -m 0755 -o pokeprice -g pokeprice /opt/pokeprice

echo "[6/7] Installation de uv dans /usr/local/bin..."
if [ ! -x /usr/local/bin/uv ]; then
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="/usr/local/bin" sh
fi
# Contexte SELinux bin_t sur /usr/local/bin/uv si SELinux est actif
if command -v restorecon >/dev/null 2>&1; then
    restorecon -Rv /usr/local/bin /opt/pokeprice /srv/pokeprice /etc/pokeprice >/dev/null 2>&1 || true
fi

echo "[7/7] Conservation du journal limitée à trois mois (adresses IP des visiteurs)..."
install -d -m 0755 /etc/systemd/journald.conf.d
printf '[Journal]\nMaxRetentionSec=3month\n' > /etc/systemd/journald.conf.d/pokeprice-retention.conf
systemctl restart systemd-journald

echo "Provisionnement système terminé avec succès."
