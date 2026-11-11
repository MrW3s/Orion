"""Use cases for the employee list story.

    As an admin or project manager I want to be able to sift through the
    list of employees using search and filters.

    Given I am on the employee list,
    when I select a role, department, or availability status filter,
    then only employees matching that filter are shown.

    Given I am on the employee list,
    when I enter an employee's name or email in the search field,
    then only employees matching that name or email are shown.

    Given no employees match my search or filters,
    when the results are displayed,
    then I see a "No employees found" message.

Employees are everyone at the agency: team members, project managers and
administrators. Clients are outside the agency, so they never appear here.
Filters combine: choosing a role and a department shows the employees who
match both. Like services.py, nothing here knows about HTTP.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db.models import Q

from common.errors import NotAllowed, UserNotFound

from .models import Availability, Profile, Role
from .services import RoleService, clean_availability, clean_department, clean_email

# The roles an employee can have, in the order the filter lists them.
EMPLOYEE_ROLES = [Role.TEAM_MEMBER, Role.PROJECT_MANAGER, Role.ADMIN]


@dataclass(frozen=True)
class EmployeeFilters:
    """What the viewer typed and picked. Blank means "don't filter on this"."""
    query: str = ""         # part of a name, username or email
    role: str = ""          # a Role value
    department: str = ""    # matched ignoring case
    availability: str = ""  # an Availability value

    @property
    def active(self) -> bool:
        return any(v.strip() for v in (self.query, self.role, self.department, self.availability))


@dataclass(frozen=True)
class EmployeeRow:
    user: object
    role: Role
    department: str
    availability: Availability

    @property
    def name(self) -> str:
        return self.user.get_full_name() or self.user.username


class EmployeeDirectory:
    def __init__(self, roles: RoleService | None = None):
        self.roles = roles or RoleService()

    def require_access(self, viewer) -> None:
        if not self.roles.can(viewer, "view_employees"):
            raise NotAllowed("Only project managers and administrators can view the employee list")

    def search(self, viewer, filters: EmployeeFilters = EmployeeFilters()) -> list[EmployeeRow]:
        self.require_access(viewer)
        users = (get_user_model().objects.select_related("profile")
                 .filter(self._employees())
                 .filter(self._matching(filters))
                 .order_by("first_name", "last_name", "username"))
        return [self._row(u) for u in users]

    def count(self, viewer) -> int:
        self.require_access(viewer)
        return get_user_model().objects.filter(self._employees()).count()

    def departments(self, viewer) -> list[str]:
        """Every department an employee belongs to, for the department filter."""
        self.require_access(viewer)
        names = (Profile.objects.filter(user__in=get_user_model().objects.filter(self._employees()))
                 .exclude(department="").values_list("department", flat=True))
        unique = {n.strip().casefold(): n.strip() for n in names}  # "Design" and "design" are one
        return sorted(unique.values(), key=str.casefold)

    def update_details(self, admin, user_id: int, *, first_name: str = "", last_name: str = "",
                       email: str = "", department: str = "",
                       availability: str = Availability.AVAILABLE) -> EmployeeRow:
        """Admins keep each person's name, email, department and availability up to
        date, so the search and filters have something to match."""
        self.roles.require_admin(admin)
        User = get_user_model()
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise UserNotFound(f"User {user_id} does not exist") from None

        user.first_name, user.last_name = first_name.strip(), last_name.strip()
        user.email = clean_email(email)
        department = clean_department(department)
        availability = clean_availability(availability)
        user.save(update_fields=["first_name", "last_name", "email"])
        Profile.objects.update_or_create(
            user=user, defaults={"department": department, "availability": availability})
        return self._row(User.objects.select_related("profile").get(pk=user.pk))

    # --- queries ---------------------------------------------------------------

    @staticmethod
    def _has_role(role: str) -> Q:
        """Users whose RoleService.role_of() is `role`, as a database query."""
        if role == Role.ADMIN:
            return Q(is_superuser=True) | Q(profile__role=Role.ADMIN)
        if role == Role.TEAM_MEMBER:  # no Profile row means team member
            return Q(is_superuser=False) & (Q(profile__isnull=True) | Q(profile__role=role))
        return Q(is_superuser=False, profile__role=role)

    def _employees(self) -> Q:
        return ~(Q(is_superuser=False) & Q(profile__role=Role.CLIENT))

    def _matching(self, f: EmployeeFilters) -> Q:
        q = Q()
        # Every word must match somewhere, so "jane doe" finds Jane Doe.
        for word in f.query.split():
            q &= (Q(username__icontains=word) | Q(first_name__icontains=word)
                  | Q(last_name__icontains=word) | Q(email__icontains=word))
        if f.role.strip():
            q &= self._has_role(f.role.strip())
        if f.department.strip():
            q &= Q(profile__department__iexact=clean_department(f.department))
        if f.availability.strip():
            value = f.availability.strip()
            if value == Availability.AVAILABLE:  # no Profile row means available
                q &= Q(profile__isnull=True) | Q(profile__availability=value)
            else:
                q &= Q(profile__availability=value)
        return q

    def _row(self, user) -> EmployeeRow:
        try:
            profile = user.profile
            department, availability = profile.department, Availability(profile.availability)
        except Profile.DoesNotExist:
            department, availability = "", Availability.AVAILABLE
        return EmployeeRow(user, self.roles.role_of(user), department, availability)
