from rest_framework.permissions import BasePermission

from common.models import PersonalAccessToken
from common.scopes import _parsed


class HasBopEventGatewayScope(BasePermission):
    """
    Permission enforcing strict scope boundaries for the Bop Event Gateway.

    Accepted scopes:
    - 'integrations:write'
    - '*:write' (intentional super-scope)

    Rejected:
    - Empty/unrestricted scopes ([])
    - Read-only scopes (e.g. 'integrations:read', '*:read')
    - Unrelated scopes (e.g. 'leads:write', 'accounts:write')
    - Tokens without bound source_app (CRM-I1B.2)
    """

    message = "Bop event gateway requires explicit 'integrations:write' or '*:write' scope."

    def has_permission(self, request, view):
        pat = getattr(request, "_pat", None)
        if pat is None:
            auth = getattr(request, "auth", None)
            if isinstance(auth, PersonalAccessToken):
                pat = auth

        if not pat or not isinstance(pat, PersonalAccessToken):
            return False

        # Reject empty / unrestricted PAT scopes ([])
        if not pat.scopes:
            return False

        held = _parsed(pat.scopes)
        if not ("integrations:write" in held or "*:write" in held):
            return False

        # CRM-I1B.2: Legacy PAT with source_app=NULL MUST be rejected by the Bop event gateway
        if not getattr(pat, "source_app", None):
            self.message = "Authenticated token is not bound to a Bop source application."
            return False

        return True
