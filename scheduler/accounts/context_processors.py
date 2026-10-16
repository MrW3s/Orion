from .services import RoleService


def roles(request):
    """Lets every page know whether to show admin-only links."""
    return {"is_admin": RoleService().can(request.user, "manage_users")}
