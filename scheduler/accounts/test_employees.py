"""Tests for the employee list story (given / when / then):

    Given I am an admin or PM on the employee list,
    when I filter by role, department or availability, or search by name or email,
    then only the matching employees are shown.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from common.errors import InvalidFilter, InvalidUser, NotAllowed, NotAnAdmin

from .models import Availability, Profile, Role
from .services import EmployeeDirectory

User = get_user_model()


def make(username, role=None, first="", last="", email="", department="", availability=None):
    user = User.objects.create_user(username, password="pw", first_name=first,
                                    last_name=last, email=email)
    if role or department or availability:
        Profile.objects.create(user=user, role=role or Role.TEAM_MEMBER, department=department,
                               availability=availability or Availability.AVAILABLE)
    return user


class Fixture(TestCase):
    def setUp(self):
        self.admin = make("ada", Role.ADMIN, "Ada", "Lovelace", "ada@orion.test", "Operations")
        self.pm = make("pat", Role.PROJECT_MANAGER, "Pat", "Kim", "pat@orion.test", "Design",
                       Availability.LIMITED)
        self.jane = make("jdoe", Role.TEAM_MEMBER, "Jane", "Doe", "jane.doe@orion.test",
                         "Engineering")
        self.bob = make("bob", Role.TEAM_MEMBER, "Bob", "Stone", "bob@agency.test", "engineering",
                        Availability.UNAVAILABLE)
        self.noprofile = make("newbie", first="Nina", last="Newman")  # no Profile row at all
        self.client_user = make("acme", Role.CLIENT, "Acme", "Corp", "buyer@acme.test")
        self.directory = EmployeeDirectory()

    def names(self, **filters):
        return [r.user.username for r in self.directory.search(self.pm, **filters)]

    def page(self, user=None, **params):
        self.client.force_login(user or self.pm)
        return self.client.get(reverse("employees"), params)

    def page_names(self, **params):
        return [r.user.username for r in self.page(**params).context["rows"]]


class WhoCanSeeTheList(Fixture):
    def test_admins_and_pms_can_open_the_list(self):
        for user in (self.admin, self.pm):
            self.assertEqual(self.page(user).status_code, 200)

    def test_team_members_and_clients_are_denied(self):
        for user in (self.jane, self.client_user):
            self.assertEqual(self.page(user).status_code, 403)
            with self.assertRaises(NotAllowed):
                self.directory.search(user)

    def test_logged_out_visitor_is_sent_to_login(self):
        response = self.client.get(reverse("employees"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('employees')}")

    def test_nav_link_only_for_admins_and_pms(self):
        self.client.force_login(self.pm)
        self.assertContains(self.client.get(reverse("home")), reverse("employees"))
        self.client.force_login(self.jane)
        self.assertNotContains(self.client.get(reverse("home")), reverse("employees"))


class NoFilters(Fixture):
    def test_lists_every_employee_but_not_clients(self):
        self.assertEqual(self.names(), ["jdoe", "pat", "ada", "newbie", "bob"])  # by last name

    def test_inactive_users_are_hidden(self):
        User.objects.filter(pk=self.bob.pk).update(is_active=False)
        self.assertNotIn("bob", self.names())


class Search(Fixture):
    def test_by_first_or_last_name(self):
        self.assertEqual(self.names(q="jane"), ["jdoe"])
        self.assertEqual(self.names(q="STONE"), ["bob"])

    def test_full_name_matches_word_by_word(self):
        self.assertEqual(self.names(q="jane doe"), ["jdoe"])
        self.assertEqual(self.names(q="jane stone"), [])

    def test_by_username(self):
        self.assertEqual(self.names(q="newb"), ["newbie"])

    def test_by_email_or_part_of_it(self):
        self.assertEqual(self.names(q="jane.doe@orion.test"), ["jdoe"])
        self.assertEqual(self.names(q="@agency.test"), ["bob"])

    def test_search_never_finds_clients(self):
        self.assertEqual(self.names(q="acme"), [])

    def test_blank_search_shows_everyone(self):
        self.assertEqual(len(self.names(q="   ")), 5)


class Filters(Fixture):
    def test_by_role(self):
        self.assertEqual(self.names(role=Role.PROJECT_MANAGER), ["pat"])
        self.assertEqual(self.names(role=Role.ADMIN), ["ada"])

    def test_team_member_filter_includes_users_without_a_profile(self):
        self.assertEqual(self.names(role=Role.TEAM_MEMBER), ["jdoe", "newbie", "bob"])

    def test_superuser_counts_as_admin(self):
        User.objects.create_superuser("root", password="pw")  # no Profile row
        self.assertEqual(sorted(self.names(role=Role.ADMIN)), ["ada", "root"])
        self.assertNotIn("root", self.names(role=Role.TEAM_MEMBER))

    def test_by_department_ignoring_case(self):
        self.assertEqual(self.names(department="Engineering"), ["jdoe", "bob"])
        self.assertEqual(self.names(department="DESIGN"), ["pat"])

    def test_by_availability(self):
        self.assertEqual(self.names(availability=Availability.UNAVAILABLE), ["bob"])
        self.assertEqual(self.names(availability=Availability.LIMITED), ["pat"])

    def test_available_includes_users_without_a_profile(self):
        self.assertEqual(self.names(availability=Availability.AVAILABLE), ["jdoe", "ada", "newbie"])

    def test_filters_and_search_combine(self):
        self.assertEqual(self.names(department="engineering", availability=Availability.AVAILABLE),
                         ["jdoe"])
        self.assertEqual(self.names(q="orion.test", role=Role.TEAM_MEMBER), ["jdoe"])
        self.assertEqual(self.names(q="bob", role=Role.ADMIN), [])

    def test_unknown_role_or_availability_is_rejected(self):
        for filters in ({"role": "boss"}, {"role": Role.CLIENT}, {"availability": "asleep"}):
            with self.assertRaises(InvalidFilter):
                self.directory.search(self.pm, **filters)

    def test_department_dropdown_lists_each_department_once(self):
        self.assertEqual(self.directory.departments(self.pm), ["Design", "Engineering", "Operations"])


class Page(Fixture):
    def test_query_string_filters_the_page(self):
        self.assertEqual(self.page_names(q="jane", role=Role.TEAM_MEMBER), ["jdoe"])
        self.assertEqual(self.page_names(department="engineering"), ["jdoe", "bob"])

    def test_page_shows_the_details_and_count(self):
        response = self.page(q="doe")
        self.assertContains(response, "Jane Doe")
        self.assertContains(response, "jane.doe@orion.test")
        self.assertContains(response, "Engineering")
        self.assertContains(response, "Showing 1 of 5 employees")

    def test_filters_stay_selected(self):
        response = self.page(role=Role.PROJECT_MANAGER, q="pat")
        self.assertContains(response, 'value="pat"')
        self.assertContains(response, '<option value="project_manager" selected>')

    def test_no_matches_shows_no_employees_found(self):
        # Given no employees match my search or filters, when the results are
        # displayed, then I see a "No employees found" message (sprint 2, story 3)
        for params in ({"q": "zzzz"}, {"department": "Design", "availability": "unavailable"}):
            response = self.page(**params)
            self.assertEqual(response.context["rows"], [])
            self.assertContains(response, "No employees found")
            self.assertContains(response, "Showing 0 of 5 employees")

    def test_story3_test_case_1_team_members_in_design(self):
        make("dee", Role.TEAM_MEMBER, "Dee", "Signer", "dee@orion.test", "Design")
        response = self.page(role=Role.TEAM_MEMBER, department="Design")
        self.assertEqual([r.user.username for r in response.context["rows"]], ["dee"])
        self.assertContains(response, "Showing 1 of 6 employees")

    def test_story1_test_case_2_html_search_is_plain_text(self):
        # Searching for an <img onerror> payload finds nobody and is shown escaped
        payload = "<img src=x onerror=alert('XSS')>"
        response = self.page(q=payload)
        self.assertContains(response, "No employees found")
        self.assertNotContains(response, payload)

    def test_bad_filter_shows_error_and_everyone(self):
        response = self.page(role="boss")
        self.assertContains(response, "Unknown role")
        self.assertEqual(len(response.context["rows"]), 5)

    def test_search_text_is_escaped(self):
        response = self.page(q="<script>alert(1)</script>")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")

    def test_only_admins_see_edit_and_add_links(self):
        edit = reverse("employee-details", args=[self.jane.pk])
        self.assertContains(self.page(self.admin), edit)
        self.assertContains(self.page(self.admin), "+ Add a user")
        self.assertNotContains(self.page(self.pm), edit)
        self.assertNotContains(self.page(self.pm), "+ Add a user")

    def test_manage_users_links_to_edit_details(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("manage-users"))
        self.assertContains(response, reverse("employee-details", args=[self.jane.pk]))


class AdminEditsDetails(Fixture):
    def post(self, user, target, **fields):
        self.client.force_login(user)
        data = {"first_name": "", "last_name": "", "email": "", "department": "",
                "availability": Availability.AVAILABLE}
        data.update(fields)
        return self.client.post(reverse("employee-details", args=[target.pk]), data, follow=True)

    def test_admin_sets_details_that_the_list_then_filters_on(self):
        response = self.post(self.admin, self.noprofile, first_name="Nina", last_name="Newman",
                             email="nina@orion.test", department="Design",
                             availability=Availability.LIMITED)
        self.assertContains(response, "Saved newbie&#x27;s details.")
        self.assertEqual(self.names(department="design", availability=Availability.LIMITED),
                         ["pat", "newbie"])
        self.assertEqual(self.names(q="nina@orion"), ["newbie"])
        self.assertEqual(self.directory._row(User.objects.get(pk=self.noprofile.pk)).role,
                         Role.TEAM_MEMBER)  # creating the profile didn't change their role

    def test_editing_keeps_the_role(self):
        self.post(self.admin, self.pm, department="Product")
        self.assertEqual(self.names(role=Role.PROJECT_MANAGER, department="product"), ["pat"])

    def test_pm_and_team_member_cannot_edit(self):
        for user in (self.pm, self.jane):
            self.assertEqual(self.post(user, self.bob, department="Hacked").status_code, 403)
            with self.assertRaises(NotAnAdmin):
                self.directory.update_details(user, self.bob.pk, department="Hacked")
        self.assertEqual(Profile.objects.get(user=self.bob).department, "engineering")

    def test_duplicate_email_is_rejected_ignoring_case(self):
        response = self.post(self.admin, self.bob, email="JANE.DOE@orion.test")
        self.assertContains(response, "Another user already has the email")
        self.assertEqual(User.objects.get(pk=self.bob.pk).email, "bob@agency.test")

    def test_invalid_email_is_rejected(self):
        self.assertContains(self.post(self.admin, self.bob, email="not-an-email"),
                            "Enter a valid email address.")

    def test_html_in_department_is_rejected(self):
        with self.assertRaises(InvalidUser):
            self.directory.update_details(self.admin, self.bob.pk, department="<b>Eng</b>")
        self.assertEqual(Profile.objects.get(user=self.bob).department, "engineering")

    def test_unknown_user_goes_back_to_the_list(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("employee-details", args=[9999]), follow=True)
        self.assertContains(response, "does not exist")
