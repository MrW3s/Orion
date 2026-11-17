from .services import RoleService


def roles(request):
    """Lets every page know whether to show admin-only (and admin + PM) links."""
    roles = RoleService()
    return {"is_admin": roles.can(request.user, "manage_users"),
            "can_view_employees": roles.can(request.user, "view_employees")}
