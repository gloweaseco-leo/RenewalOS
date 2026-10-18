"""Read-only provider compatibility check; no enterprise accounts provisioned."""
import json
import sys
from renewalos.oidc import OIDCConfig, OIDCRejected
from renewalos.provider_probe import inspect_provider


def main():
    try:
        result = inspect_provider(OIDCConfig.from_env())
    except (OIDCRejected, OSError) as exc:
        print(json.dumps({'provider_contract':'FAIL','public_release':'NO_GO',
                          'reason':'OIDC_PROVIDER_UNVERIFIED'},sort_keys=True))
        return 2
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
