"""Resolve the relay's canonical origin from explicit or Coolify configuration."""
from urllib.parse import urlsplit


def runtime_origin(env):
    key = 'FLIGHT_PUBLIC_ORIGIN'

    def parse(value, label):
        try:
            value = value.strip()
            url = urlsplit(value)
            if (not value or any(c.isspace() for c in value)
                    or url.scheme not in ('http', 'https') or not url.hostname
                    or url.username is not None or url.password is not None
                    or url.path not in ('', '/') or url.query or url.fragment):
                raise ValueError()
            port = url.port
            host = url.hostname
            authority = f'[{host}]' if ':' in host else host
            if port is not None and (url.scheme, port) not in (('http', 80), ('https', 443)):
                authority += f':{port}'
            return url.scheme, host, authority, f'{url.scheme}://{authority}'
        except ValueError:
            raise ValueError(f'{label} must contain HTTP(S) origins without credentials, paths or query parameters') from None

    if key in env:
        return parse(env[key], key)[3]
    if not env.get('COOLIFY_URL', '').strip():
        raise ValueError(f'Set {key} or enable Coolify default variables and configure a domain')
    urls = [parse(value, 'COOLIFY_URL') for value in env['COOLIFY_URL'].split(',')]
    families = {(scheme, authority.removeprefix('www.')) for scheme, host, authority, value in urls}
    if len(families) != 1:
        raise ValueError(f'COOLIFY_URL contains unrelated origins; set {key} to the canonical origin')
    return next((value for scheme, host, authority, value in urls if not host.startswith('www.')), urls[0][3])
