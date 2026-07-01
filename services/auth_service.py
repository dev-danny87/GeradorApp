import logging
import re
import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from typing import Tuple, Optional
from urllib.parse import urljoin

from redmine_mappings import LOGIN_TO_USER_ID

SSP_BASE_URL = "https://redmine.ssp.go.gov.br"
PGE_BASE_URL = "https://projetos.procuradoria.go.gov.br/contrato17"
IPHAN_BASE_URL = "https://redmine.iphan.gov.br/redmine"
PGE_LOGIN_URL = f"{PGE_BASE_URL}/login"
IPHAN_LOGIN_URL = f"{IPHAN_BASE_URL}/login"

# IPHAN uses a certificate chain not present in the default CA bundle on some machines.
_SSL_VERIFY_DISABLED_HOSTS = {IPHAN_BASE_URL}

# Backward compatibility
BASE_URL = SSP_BASE_URL

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def _configure_session_ssl(session: requests.Session, base_url: str) -> None:
    if base_url in _SSL_VERIFY_DISABLED_HOSTS:
        session.verify = False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.warning(
            "Verificação SSL desabilitada para %s (certificado não confiável pelo repositório local de CAs).",
            base_url,
        )


def _resolve_user_id(username: str, base_url: str, soup: Optional[BeautifulSoup] = None) -> Optional[str]:
    user_id = LOGIN_TO_USER_ID.get(username)
    if user_id:
        return str(user_id)
    if soup is None:
        return None
    logged_as = soup.find("div", attrs={"id": "loggedas"})
    if not logged_as:
        return None
    link = logged_as.find("a", class_="user")
    if not link:
        return None
    href = link.get("href", "")
    m = re.search(r"/users/(\d+)", href)
    return m.group(1) if m else None


def check_user_permissions(
    session: requests.Session,
    username: str,
    base_url: str = SSP_BASE_URL,
    soup: Optional[BeautifulSoup] = None,
) -> bool:
    """Verifies if the user has the 'Gestor' role on the given Redmine instance."""
    logger.info("Verificando permissões de Gestor no perfil...")

    try:
        user_id = _resolve_user_id(username, base_url, soup)
        if not user_id:
            logger.error(f"Usuário '{username}' não encontrado no mapeamento e ID não extraído da sessão.")
            return False

        url = f"{base_url}/users/{user_id}"
        response = session.get(url, timeout=30)
        response.raise_for_status()

        profile_soup = BeautifulSoup(response.text, "html.parser")
        is_gestor = False

        for tr in profile_soup.select("table.list.projects tr"):
            td_roles = tr.find("td", class_="roles")
            if td_roles and "Gestor" in td_roles.get_text(strip=True):
                is_gestor = True

        if is_gestor:
            logger.info("-> ACESSO CONCEDIDO: O usuário é Gestor.")
        else:
            logger.info("-> ACESSO NEGADO: O usuário NÃO possui papel de Gestor.")

        return is_gestor

    except Exception as e:
        logger.error(f"Erro ao verificar perfil: {e}")
        return False


def login_redmine(
    username: str,
    password: str,
    base_url: str = SSP_BASE_URL,
) -> Tuple[Optional[requests.Session], str, bool]:
    """
    Authenticates a user in Redmine and checks for 'Gestor' permissions.
    Returns: (Session object, Status Message, Is_Gestor Boolean)
    """
    logger.info(f"Iniciando login para o usuário '{username}' em {base_url}...")
    session = requests.Session()

    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    _configure_session_ssl(session, base_url)

    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Referer": f"{base_url}/login",
    })

    try:
        if base_url == PGE_BASE_URL:
            login_url = PGE_LOGIN_URL
        elif base_url == IPHAN_BASE_URL:
            login_url = IPHAN_LOGIN_URL
        else:
            login_url = f"{base_url}/login"
        r_login_page = session.get(login_url, timeout=30)
        r_login_page.raise_for_status()

        soup_login = BeautifulSoup(r_login_page.text, "html.parser")

        login_payload = {
            "username": username,
            "password": password,
            "autologin": "1",
            "commit": "Entrar",
        }

        login_form = soup_login.find("form", action=lambda x: x and "login" in x.lower())
        if not login_form:
            return None, "Não foi possível localizar o formulário de login na página.", False

        form_action = login_form.get("action", "")
        post_url = urljoin(base_url + "/", form_action) if form_action else login_url

        for hidden_input in login_form.find_all("input", type="hidden"):
            name = hidden_input.get("name")
            value = hidden_input.get("value", "")
            if name and name not in login_payload:
                login_payload[name] = value

        csrf_meta = soup_login.find("meta", attrs={"name": "csrf-token"})
        if csrf_meta:
            login_payload["authenticity_token"] = csrf_meta.get("content")

        if "authenticity_token" not in login_payload:
            return None, "Não foi possível capturar o token de segurança (authenticity_token).", False

        if "back_url" in login_payload:
            login_payload["back_url"] = f"{base_url}/"

        r_login_post = session.post(post_url, data=login_payload, timeout=30)
        r_login_post.raise_for_status()

        if "/login" in r_login_post.url:
            soup_result = BeautifulSoup(r_login_post.text, "html.parser")
            error_flash = soup_result.find("div", class_="flash error")
            error_msg = error_flash.get_text(strip=True) if error_flash else "Credenciais rejeitadas ou erro de sessão."
            logger.warning(f"Falha no Login: {error_msg}")
            return None, error_msg, False

        soup_result = BeautifulSoup(r_login_post.text, "html.parser")
        logged_as_div = soup_result.find("div", attrs={"id": "loggedas"})
        user_logged_in = logged_as_div.get_text(strip=True) if logged_as_div else username

        logger.info(f"SUCESSO NO LOGIN -> {user_logged_in}")

        is_gestor = check_user_permissions(session, username, base_url, soup_result)
        return session, user_logged_in, is_gestor

    except requests.exceptions.RequestException as e:
        error_msg = f"Erro de rede durante o login: {e}"
        logger.error(error_msg)
        return None, error_msg, False
    except Exception as e:
        error_msg = f"Erro inesperado no login: {e}"
        logger.error(error_msg)
        return None, error_msg, False
