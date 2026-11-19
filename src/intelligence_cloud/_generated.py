"""Generated from openapi.yaml by tools/generate.py. Do not edit by hand."""
# flake8: noqa
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterator, Mapping, Optional, Sequence, Union

from ._base import Namespace, Page


class AuthAPI(Namespace):
    """Authentication operations."""

    def login(self, body: Mapping[str, Any]) -> Any:
        """Sign in. `POST /auth/login` (frontline_user)."""
        return self._c._call('login', path={}, query={}, body=body)

    def refresh(self, body: Mapping[str, Any]) -> Any:
        """Renew the access token. `POST /auth/refresh` (frontline_user)."""
        return self._c._call('refresh', path={}, query={}, body=body)

    def logout(self) -> Any:
        """Sign out. `POST /auth/logout` (frontline_user)."""
        return self._c._call('logout', path={}, query={}, body=None)


class ResellersAPI(Namespace):
    """Resellers operations."""

    def get_reseller_branding(self, reseller_id: str) -> Any:
        """Read reseller branding. `GET /resellers/{resellerId}/branding` (reseller_admin)."""
        return self._c._call('getResellerBranding', path={'resellerId': reseller_id}, query={}, body=None)

    def update_reseller_branding(self, reseller_id: str, body: Mapping[str, Any]) -> Any:
        """Update reseller branding. `PATCH /resellers/{resellerId}/branding` (reseller_admin)."""
        return self._c._call('updateResellerBranding', path={'resellerId': reseller_id}, query={}, body=body)

    def get_reseller_smtp_settings(self, reseller_id: str) -> Any:
        """Read outbound email (SMTP) settings. `GET /resellers/{resellerId}/smtp-settings` (reseller_admin)."""
        return self._c._call('getResellerSmtpSettings', path={'resellerId': reseller_id}, query={}, body=None)

    def save_reseller_smtp_settings(self, reseller_id: str, body: Mapping[str, Any]) -> Any:
        """Save outbound email (SMTP) settings. `PATCH /resellers/{resellerId}/smtp-settings` (reseller_admin)."""
        return self._c._call('saveResellerSmtpSettings', path={'resellerId': reseller_id}, query={}, body=body)

    def delete_reseller_smtp_settings(self, reseller_id: str) -> Any:
        """Remove outbound email (SMTP) settings. `DELETE /resellers/{resellerId}/smtp-settings` (reseller_admin)."""
        return self._c._call('deleteResellerSmtpSettings', path={'resellerId': reseller_id}, query={}, body=None)


class CompaniesAPI(Namespace):
    """Companies operations."""

    def list_companies(self, reseller_id: str, *, search: Optional[str] = None, is_active: Optional[bool] = None, limit: Optional[int] = None, cursor: Optional[str] = None) -> Page:
        """List customer companies. `GET /resellers/{resellerId}/companies` (reseller_admin)."""
        return self._c._page('listCompanies', path={'resellerId': reseller_id}, query={'search': search, 'is_active': is_active, 'limit': limit, 'cursor': cursor}, body=None)

    def iter_companies(self, reseller_id: str, *, search: Optional[str] = None, is_active: Optional[bool] = None) -> Iterator[Any]:
        """Every item of `list_companies`, following cursors 100 at a time."""
        return self._c._iter('listCompanies', path={'resellerId': reseller_id}, query={'search': search, 'is_active': is_active})

    def create_company(self, reseller_id: str, body: Mapping[str, Any]) -> Any:
        """Create a customer company. `POST /resellers/{resellerId}/companies` (reseller_admin)."""
        return self._c._call('createCompany', path={'resellerId': reseller_id}, query={}, body=body)

    def get_companies_mfa_summary(self, reseller_id: str) -> Any:
        """Read the MFA default for new companies. `GET /resellers/{resellerId}/companies/mfa` (reseller_admin)."""
        return self._c._call('getCompaniesMfaSummary', path={'resellerId': reseller_id}, query={}, body=None)

    def get_company(self, company_id: str) -> Any:
        """Read a company. `GET /companies/{companyId}` (reseller_admin)."""
        return self._c._call('getCompany', path={'companyId': company_id}, query={}, body=None)

    def update_company(self, company_id: str, body: Mapping[str, Any]) -> Any:
        """Update a company. `PATCH /companies/{companyId}` (reseller_admin)."""
        return self._c._call('updateCompany', path={'companyId': company_id}, query={}, body=body)

    def deactivate_company(self, company_id: str) -> Any:
        """Deactivate a company. `POST /companies/{companyId}/deactivate` (reseller_admin)."""
        return self._c._call('deactivateCompany', path={'companyId': company_id}, query={}, body=None)

    def reactivate_company(self, company_id: str) -> Any:
        """Reactivate a company. `POST /companies/{companyId}/reactivate` (reseller_admin)."""
        return self._c._call('reactivateCompany', path={'companyId': company_id}, query={}, body=None)

    def get_company_security_settings(self, company_id: str) -> Any:
        """Read a company's security settings. `GET /companies/{companyId}/security-settings` (reseller_admin)."""
        return self._c._call('getCompanySecuritySettings', path={'companyId': company_id}, query={}, body=None)

    def get_company_branding(self, company_id: str) -> Any:
        """Read company branding overrides. `GET /companies/{companyId}/branding` (reseller_admin)."""
        return self._c._call('getCompanyBranding', path={'companyId': company_id}, query={}, body=None)

    def update_company_branding(self, company_id: str, body: Mapping[str, Any]) -> Any:
        """Update company branding overrides. `PATCH /companies/{companyId}/branding` (reseller_admin)."""
        return self._c._call('updateCompanyBranding', path={'companyId': company_id}, query={}, body=body)


class SsoAPI(Namespace):
    """Single sign-on operations."""

    def list_company_domains(self, company_id: str) -> Any:
        """List claimed domains. `GET /companies/{companyId}/domains` (reseller_admin)."""
        return self._c._call('listCompanyDomains', path={'companyId': company_id}, query={}, body=None)

    def claim_company_domain(self, company_id: str, body: Mapping[str, Any]) -> Any:
        """Claim a domain. `POST /companies/{companyId}/domains` (reseller_admin)."""
        return self._c._call('claimCompanyDomain', path={'companyId': company_id}, query={}, body=body)

    def remove_company_domain(self, company_id: str, domain_id: str) -> Any:
        """Remove a domain claim. `DELETE /companies/{companyId}/domains/{domainId}` (reseller_admin)."""
        return self._c._call('removeCompanyDomain', path={'companyId': company_id, 'domainId': domain_id}, query={}, body=None)

    def list_domain_verifications(self, company_id: str, domain_id: str) -> Any:
        """List verification attempts. `GET /companies/{companyId}/domains/{domainId}/verifications` (reseller_admin)."""
        return self._c._call('listDomainVerifications', path={'companyId': company_id, 'domainId': domain_id}, query={}, body=None)

    def verify_domain(self, company_id: str, domain_id: str) -> Any:
        """Check the TXT record now. `POST /companies/{companyId}/domains/{domainId}/verifications` (reseller_admin)."""
        return self._c._call('verifyDomain', path={'companyId': company_id, 'domainId': domain_id}, query={}, body=None)

    def get_identity_provider(self, company_id: str) -> Any:
        """Read the identity provider connection. `GET /companies/{companyId}/identity-provider` (reseller_admin)."""
        return self._c._call('getIdentityProvider', path={'companyId': company_id}, query={}, body=None)

    def connect_identity_provider(self, company_id: str, body: Mapping[str, Any]) -> Any:
        """Connect an OpenID Connect provider. `POST /companies/{companyId}/identity-provider` (reseller_admin)."""
        return self._c._call('connectIdentityProvider', path={'companyId': company_id}, query={}, body=body)

    def disconnect_identity_provider(self, company_id: str) -> Any:
        """Disconnect the identity provider. `DELETE /companies/{companyId}/identity-provider` (reseller_admin)."""
        return self._c._call('disconnectIdentityProvider', path={'companyId': company_id}, query={}, body=None)

    def test_identity_provider(self, company_id: str) -> Any:
        """Test the identity provider connection. `POST /companies/{companyId}/identity-provider/test` (reseller_admin)."""
        return self._c._call('testIdentityProvider', path={'companyId': company_id}, query={}, body=None)


class ProductsAPI(Namespace):
    """Products operations."""

    def list_products(self) -> Any:
        """List products. `GET /products` (reseller_admin)."""
        return self._c._call('listProducts', path={}, query={}, body=None)

    def list_company_products(self, company_id: str) -> Any:
        """Company products. `GET /companies/{companyId}/products` (reseller_admin)."""
        return self._c._call('listCompanyProducts', path={'companyId': company_id}, query={}, body=None)

    def list_user_products(self, company_id: str, user_id: str) -> Any:
        """A user's products. `GET /companies/{companyId}/users/{userId}/products` (reseller_admin)."""
        return self._c._call('listUserProducts', path={'companyId': company_id, 'userId': user_id}, query={}, body=None)

    def enable_user_product(self, location_id: str, user_id: str, product_key: str) -> Any:
        """Turn a product on for a user. `POST /locations/{locationId}/users/{userId}/products/{productKey}/enable` (reseller_admin)."""
        return self._c._call('enableUserProduct', path={'locationId': location_id, 'userId': user_id, 'productKey': product_key}, query={}, body=None)

    def disable_user_product(self, location_id: str, user_id: str, product_key: str) -> Any:
        """Turn a product off for a user. `POST /locations/{locationId}/users/{userId}/products/{productKey}/disable` (reseller_admin)."""
        return self._c._call('disableUserProduct', path={'locationId': location_id, 'userId': user_id, 'productKey': product_key}, query={}, body=None)


class LocationsAPI(Namespace):
    """Locations operations."""

    def list_verticals(self) -> Any:
        """List industries. `GET /verticals` (reseller_admin)."""
        return self._c._call('listVerticals', path={}, query={}, body=None)

    def list_company_locations(self, company_id: str, *, search: Optional[str] = None, is_active: Optional[bool] = None, limit: Optional[int] = None, cursor: Optional[str] = None, offset: Optional[int] = None) -> Page:
        """List a company's locations. `GET /companies/{companyId}/locations` (reseller_admin)."""
        return self._c._page('listCompanyLocations', path={'companyId': company_id}, query={'search': search, 'is_active': is_active, 'limit': limit, 'cursor': cursor, 'offset': offset}, body=None)

    def iter_company_locations(self, company_id: str, *, search: Optional[str] = None, is_active: Optional[bool] = None, offset: Optional[int] = None) -> Iterator[Any]:
        """Every item of `list_company_locations`, following cursors 100 at a time."""
        return self._c._iter('listCompanyLocations', path={'companyId': company_id}, query={'search': search, 'is_active': is_active, 'offset': offset})

    def create_location(self, company_id: str, body: Mapping[str, Any]) -> Any:
        """Create a location. `POST /companies/{companyId}/locations` (reseller_admin)."""
        return self._c._call('createLocation', path={'companyId': company_id}, query={}, body=body)

    def get_location(self, company_id: str, location_id: str) -> Any:
        """Read a location. `GET /companies/{companyId}/locations/{locationId}` (reseller_admin)."""
        return self._c._call('getLocation', path={'companyId': company_id, 'locationId': location_id}, query={}, body=None)

    def update_location(self, company_id: str, location_id: str, body: Mapping[str, Any]) -> Any:
        """Update a location. `PATCH /companies/{companyId}/locations/{locationId}` (reseller_admin)."""
        return self._c._call('updateLocation', path={'companyId': company_id, 'locationId': location_id}, query={}, body=body)

    def deactivate_location(self, company_id: str, location_id: str) -> Any:
        """Deactivate a location. `POST /companies/{companyId}/locations/{locationId}/deactivate` (reseller_admin)."""
        return self._c._call('deactivateLocation', path={'companyId': company_id, 'locationId': location_id}, query={}, body=None)

    def reactivate_location(self, company_id: str, location_id: str) -> Any:
        """Reactivate a location. `POST /companies/{companyId}/locations/{locationId}/reactivate` (reseller_admin)."""
        return self._c._call('reactivateLocation', path={'companyId': company_id, 'locationId': location_id}, query={}, body=None)


class GroupsAPI(Namespace):
    """User groups operations."""

    def list_user_groups(self, location_id: str, *, search: Optional[str] = None, limit: Optional[int] = None, cursor: Optional[str] = None) -> Page:
        """List a location's groups. `GET /locations/{locationId}/user-groups` (reseller_admin)."""
        return self._c._page('listUserGroups', path={'locationId': location_id}, query={'search': search, 'limit': limit, 'cursor': cursor}, body=None)

    def iter_user_groups(self, location_id: str, *, search: Optional[str] = None) -> Iterator[Any]:
        """Every item of `list_user_groups`, following cursors 100 at a time."""
        return self._c._iter('listUserGroups', path={'locationId': location_id}, query={'search': search})

    def create_user_group(self, location_id: str, body: Mapping[str, Any]) -> Any:
        """Create a group. `POST /locations/{locationId}/user-groups` (reseller_admin)."""
        return self._c._call('createUserGroup', path={'locationId': location_id}, query={}, body=body)

    def get_user_group(self, location_id: str, group_id: str) -> Any:
        """Read a group with its members. `GET /locations/{locationId}/user-groups/{groupId}` (reseller_admin)."""
        return self._c._call('getUserGroup', path={'locationId': location_id, 'groupId': group_id}, query={}, body=None)

    def update_user_group(self, location_id: str, group_id: str, body: Mapping[str, Any]) -> Any:
        """Rename a group or set its members. `PATCH /locations/{locationId}/user-groups/{groupId}` (reseller_admin)."""
        return self._c._call('updateUserGroup', path={'locationId': location_id, 'groupId': group_id}, query={}, body=body)

    def delete_user_group(self, location_id: str, group_id: str, *, force: Optional[bool] = None) -> Any:
        """Delete a group. `DELETE /locations/{locationId}/user-groups/{groupId}` (reseller_admin)."""
        return self._c._call('deleteUserGroup', path={'locationId': location_id, 'groupId': group_id}, query={'force': force}, body=None)

    def get_user_group_membership(self, location_id: str, user_id: str) -> Any:
        """A user's groups at a location. `GET /locations/{locationId}/users/{userId}/group-membership` (reseller_admin)."""
        return self._c._call('getUserGroupMembership', path={'locationId': location_id, 'userId': user_id}, query={}, body=None)

    def set_user_group_membership(self, location_id: str, user_id: str, body: Mapping[str, Any]) -> Any:
        """Set a user's groups at a location. `PUT /locations/{locationId}/users/{userId}/group-membership` (reseller_admin)."""
        return self._c._call('setUserGroupMembership', path={'locationId': location_id, 'userId': user_id}, query={}, body=body)


class ConnectorsAPI(Namespace):
    """Connectors operations."""

    def list_connector_types(self) -> Any:
        """List connector types. `GET /connector-types` (reseller_admin)."""
        return self._c._call('listConnectorTypes', path={}, query={}, body=None)

    def test_connector(self, location_id: str, body: Mapping[str, Any]) -> Any:
        """Dry-run a connector. `POST /locations/{locationId}/connectors/test` (reseller_admin)."""
        return self._c._call('testConnector', path={'locationId': location_id}, query={}, body=body)

    def list_location_connectors(self, location_id: str, *, search: Optional[str] = None, status: Optional[str] = None, limit: Optional[int] = None, cursor: Optional[str] = None) -> Page:
        """List a location's connectors. `GET /locations/{locationId}/connectors` (reseller_admin)."""
        return self._c._page('listLocationConnectors', path={'locationId': location_id}, query={'search': search, 'status': status, 'limit': limit, 'cursor': cursor}, body=None)

    def iter_location_connectors(self, location_id: str, *, search: Optional[str] = None, status: Optional[str] = None) -> Iterator[Any]:
        """Every item of `list_location_connectors`, following cursors 100 at a time."""
        return self._c._iter('listLocationConnectors', path={'locationId': location_id}, query={'search': search, 'status': status})

    def create_connector(self, location_id: str, body: Mapping[str, Any]) -> Any:
        """Create a connector. `POST /locations/{locationId}/connectors` (reseller_admin)."""
        return self._c._call('createConnector', path={'locationId': location_id}, query={}, body=body)

    def get_connector(self, location_id: str, connector_id: str) -> Any:
        """Read a connector. `GET /locations/{locationId}/connectors/{connectorId}` (reseller_admin)."""
        return self._c._call('getConnector', path={'locationId': location_id, 'connectorId': connector_id}, query={}, body=None)

    def update_connector(self, location_id: str, connector_id: str, body: Mapping[str, Any]) -> Any:
        """Update a connector. `PATCH /locations/{locationId}/connectors/{connectorId}` (reseller_admin)."""
        return self._c._call('updateConnector', path={'locationId': location_id, 'connectorId': connector_id}, query={}, body=body)

    def deactivate_connector(self, location_id: str, connector_id: str) -> Any:
        """Stop a connector. `POST /locations/{locationId}/connectors/{connectorId}/deactivate` (reseller_admin)."""
        return self._c._call('deactivateConnector', path={'locationId': location_id, 'connectorId': connector_id}, query={}, body=None)

    def reactivate_connector(self, location_id: str, connector_id: str) -> Any:
        """Restart a connector. `POST /locations/{locationId}/connectors/{connectorId}/reactivate` (reseller_admin)."""
        return self._c._call('reactivateConnector', path={'locationId': location_id, 'connectorId': connector_id}, query={}, body=None)

    def list_company_connectors(self, company_id: str, *, search: Optional[str] = None, status: Optional[str] = None, type: Optional[str] = None, limit: Optional[int] = None, cursor: Optional[str] = None) -> Page:
        """List a company's connectors. `GET /companies/{companyId}/connectors` (reseller_admin)."""
        return self._c._page('listCompanyConnectors', path={'companyId': company_id}, query={'search': search, 'status': status, 'type': type, 'limit': limit, 'cursor': cursor}, body=None)

    def iter_company_connectors(self, company_id: str, *, search: Optional[str] = None, status: Optional[str] = None, type: Optional[str] = None) -> Iterator[Any]:
        """Every item of `list_company_connectors`, following cursors 100 at a time."""
        return self._c._iter('listCompanyConnectors', path={'companyId': company_id}, query={'search': search, 'status': status, 'type': type})


class FirstAlertAPI(Namespace):
    """First Alert operations."""

    def list_alert_rules(self, location_id: str, *, limit: Optional[int] = None, cursor: Optional[str] = None) -> Page:
        """List a location's alert rules. `GET /locations/{locationId}/first-alert/rules` (reseller_admin)."""
        return self._c._page('listAlertRules', path={'locationId': location_id}, query={'limit': limit, 'cursor': cursor}, body=None)

    def iter_alert_rules(self, location_id: str) -> Iterator[Any]:
        """Every item of `list_alert_rules`, following cursors 100 at a time."""
        return self._c._iter('listAlertRules', path={'locationId': location_id}, query={})

    def create_alert_rule(self, location_id: str, body: Mapping[str, Any]) -> Any:
        """Create an alert rule. `POST /locations/{locationId}/first-alert/rules` (reseller_admin)."""
        return self._c._call('createAlertRule', path={'locationId': location_id}, query={}, body=body)

    def get_alert_rule(self, location_id: str, rule_id: str) -> Any:
        """Read an alert rule. `GET /locations/{locationId}/first-alert/rules/{ruleId}` (reseller_admin)."""
        return self._c._call('getAlertRule', path={'locationId': location_id, 'ruleId': rule_id}, query={}, body=None)

    def update_alert_rule(self, location_id: str, rule_id: str, body: Mapping[str, Any]) -> Any:
        """Update an alert rule. `PATCH /locations/{locationId}/first-alert/rules/{ruleId}` (reseller_admin)."""
        return self._c._call('updateAlertRule', path={'locationId': location_id, 'ruleId': rule_id}, query={}, body=body)

    def delete_alert_rule(self, location_id: str, rule_id: str) -> Any:
        """Delete an alert rule. `DELETE /locations/{locationId}/first-alert/rules/{ruleId}` (reseller_admin)."""
        return self._c._call('deleteAlertRule', path={'locationId': location_id, 'ruleId': rule_id}, query={}, body=None)

    def duplicate_alert_rule(self, location_id: str, rule_id: str) -> Any:
        """Copy an alert rule. `POST /locations/{locationId}/first-alert/rules/{ruleId}/duplicate` (reseller_admin)."""
        return self._c._call('duplicateAlertRule', path={'locationId': location_id, 'ruleId': rule_id}, query={}, body=None)

    def get_first_alert_config(self, location_id: str) -> Any:
        """Read monitored numbers and the alert webhook. `GET /locations/{locationId}/first-alert/config` (reseller_admin)."""
        return self._c._call('getFirstAlertConfig', path={'locationId': location_id}, query={}, body=None)

    def save_first_alert_config(self, location_id: str, body: Mapping[str, Any]) -> Any:
        """Set monitored numbers and the alert webhook. `PUT /locations/{locationId}/first-alert/config` (reseller_admin)."""
        return self._c._call('saveFirstAlertConfig', path={'locationId': location_id}, query={}, body=body)

    def test_first_alert_webhook(self, location_id: str, body: Mapping[str, Any]) -> Any:
        """Test the alert webhook. `POST /locations/{locationId}/first-alert/config/test-webhook` (reseller_admin)."""
        return self._c._call('testFirstAlertWebhook', path={'locationId': location_id}, query={}, body=body)

    def get_alert_notification_preferences(self, location_id: str, user_id: str) -> Any:
        """Read a user's alert email and digest. `GET /locations/{locationId}/users/{userId}/first-alert/notification-preferences` (reseller_admin)."""
        return self._c._call('getAlertNotificationPreferences', path={'locationId': location_id, 'userId': user_id}, query={}, body=None)

    def set_alert_email_preferences(self, location_id: str, user_id: str, body: Mapping[str, Any]) -> Any:
        """Set a user's alert email. `PUT /locations/{locationId}/users/{userId}/first-alert/email-preferences` (reseller_admin)."""
        return self._c._call('setAlertEmailPreferences', path={'locationId': location_id, 'userId': user_id}, query={}, body=body)

    def set_alert_digest_preferences(self, location_id: str, user_id: str, body: Mapping[str, Any]) -> Any:
        """Set a user's alert digest. `PUT /locations/{locationId}/users/{userId}/first-alert/digest-preferences` (reseller_admin)."""
        return self._c._call('setAlertDigestPreferences', path={'locationId': location_id, 'userId': user_id}, query={}, body=body)


class InsightsHubAPI(Namespace):
    """Insights Hub operations."""

    def get_insights_hub_setup(self, location_id: str) -> Any:
        """Read Insights Hub setup. `GET /locations/{locationId}/insights-hub/setup` (reseller_admin)."""
        return self._c._call('getInsightsHubSetup', path={'locationId': location_id}, query={}, body=None)

    def save_insights_hub_setup(self, location_id: str, body: Mapping[str, Any]) -> Any:
        """Save Insights Hub setup. `POST /locations/{locationId}/insights-hub/setup` (reseller_admin)."""
        return self._c._call('saveInsightsHubSetup', path={'locationId': location_id}, query={}, body=body)

    def update_insights_hub_setup(self, location_id: str, body: Mapping[str, Any]) -> Any:
        """Update Insights Hub setup. `PATCH /locations/{locationId}/insights-hub/setup` (reseller_admin)."""
        return self._c._call('updateInsightsHubSetup', path={'locationId': location_id}, query={}, body=body)

    def get_insights_hub_config(self, location_id: str) -> Any:
        """Read Insights Hub coverage. `GET /locations/{locationId}/insights-hub/config` (reseller_admin)."""
        return self._c._call('getInsightsHubConfig', path={'locationId': location_id}, query={}, body=None)

    def update_insights_hub_config(self, location_id: str, body: Mapping[str, Any]) -> Any:
        """Set Insights Hub coverage. `PATCH /locations/{locationId}/insights-hub/config` (reseller_admin)."""
        return self._c._call('updateInsightsHubConfig', path={'locationId': location_id}, query={}, body=body)

    def get_user_insights_hub_access(self, location_id: str, user_id: str) -> Any:
        """Check a user's Insights Hub access. `GET /locations/{locationId}/users/{userId}/insights-hub/access` (reseller_admin)."""
        return self._c._call('getUserInsightsHubAccess', path={'locationId': location_id, 'userId': user_id}, query={}, body=None)


class UsersAPI(Namespace):
    """Users operations."""

    def list_company_users(self, company_id: str, *, search: Optional[str] = None, status: Optional[str] = None, role: Optional[str] = None, location_id: Optional[Union[str, Sequence[str]]] = None, limit: Optional[int] = None, cursor: Optional[str] = None) -> Page:
        """List a company's users. `GET /companies/{companyId}/users` (reseller_admin)."""
        return self._c._page('listCompanyUsers', path={'companyId': company_id}, query={'search': search, 'status': status, 'role': role, 'location_id': location_id, 'limit': limit, 'cursor': cursor}, body=None)

    def iter_company_users(self, company_id: str, *, search: Optional[str] = None, status: Optional[str] = None, role: Optional[str] = None, location_id: Optional[Union[str, Sequence[str]]] = None) -> Iterator[Any]:
        """Every item of `list_company_users`, following cursors 100 at a time."""
        return self._c._iter('listCompanyUsers', path={'companyId': company_id}, query={'search': search, 'status': status, 'role': role, 'location_id': location_id})

    def create_company_user(self, company_id: str, body: Mapping[str, Any]) -> Any:
        """Create a user. `POST /companies/{companyId}/users` (reseller_admin)."""
        return self._c._call('createCompanyUser', path={'companyId': company_id}, query={}, body=body)

    def get_company_user(self, company_id: str, user_id: str) -> Any:
        """Read a user. `GET /companies/{companyId}/users/{userId}` (reseller_admin)."""
        return self._c._call('getCompanyUser', path={'companyId': company_id, 'userId': user_id}, query={}, body=None)

    def update_company_user(self, company_id: str, user_id: str, body: Mapping[str, Any]) -> Any:
        """Update a user, role or locations. `PATCH /companies/{companyId}/users/{userId}` (reseller_admin)."""
        return self._c._call('updateCompanyUser', path={'companyId': company_id, 'userId': user_id}, query={}, body=body)

    def deactivate_company_user(self, company_id: str, user_id: str) -> Any:
        """Deactivate a user. `POST /companies/{companyId}/users/{userId}/deactivate` (reseller_admin)."""
        return self._c._call('deactivateCompanyUser', path={'companyId': company_id, 'userId': user_id}, query={}, body=None)

    def reactivate_company_user(self, company_id: str, user_id: str) -> Any:
        """Reactivate a user. `POST /companies/{companyId}/users/{userId}/reactivate` (reseller_admin)."""
        return self._c._call('reactivateCompanyUser', path={'companyId': company_id, 'userId': user_id}, query={}, body=None)

    def resend_invitation(self, company_id: str, user_id: str) -> Any:
        """Resend the invitation email. `POST /companies/{companyId}/users/{userId}/resend-invitation` (reseller_admin)."""
        return self._c._call('resendInvitation', path={'companyId': company_id, 'userId': user_id}, query={}, body=None)

    def reset_password(self, company_id: str, user_id: str) -> Any:
        """Send a password reset email. `POST /companies/{companyId}/users/{userId}/reset-password` (reseller_admin)."""
        return self._c._call('resetPassword', path={'companyId': company_id, 'userId': user_id}, query={}, body=None)

    def get_user_number_mappings(self, company_id: str, user_id: str) -> Any:
        """Read a user's numbers. `GET /companies/{companyId}/users/{userId}/connector-mappings` (reseller_admin)."""
        return self._c._call('getUserNumberMappings', path={'companyId': company_id, 'userId': user_id}, query={}, body=None)

    def set_user_number_mappings(self, company_id: str, user_id: str, body: Mapping[str, Any]) -> Any:
        """Set a user's numbers. `PUT /companies/{companyId}/users/{userId}/connector-mappings` (reseller_admin)."""
        return self._c._call('setUserNumberMappings', path={'companyId': company_id, 'userId': user_id}, query={}, body=body)

    def list_location_users(self, location_id: str, *, search: Optional[str] = None, status: Optional[str] = None, limit: Optional[int] = None, cursor: Optional[str] = None) -> Page:
        """List a location's users with products and groups. `GET /locations/{locationId}/users` (reseller_admin)."""
        return self._c._page('listLocationUsers', path={'locationId': location_id}, query={'search': search, 'status': status, 'limit': limit, 'cursor': cursor}, body=None)

    def iter_location_users(self, location_id: str, *, search: Optional[str] = None, status: Optional[str] = None) -> Iterator[Any]:
        """Every item of `list_location_users`, following cursors 100 at a time."""
        return self._c._iter('listLocationUsers', path={'locationId': location_id}, query={'search': search, 'status': status})

    def get_location_user(self, location_id: str, user_id: str) -> Any:
        """Read a user at a location. `GET /locations/{locationId}/users/{userId}` (reseller_admin)."""
        return self._c._call('getLocationUser', path={'locationId': location_id, 'userId': user_id}, query={}, body=None)


class AfterCallSettingsAPI(Namespace):
    """After Call settings operations."""

    def get_user_after_call_settings(self, location_id: str, user_id: str) -> Any:
        """Read a user's After Call settings. `GET /locations/{locationId}/users/{userId}/after-call-settings` (reseller_admin)."""
        return self._c._call('getUserAfterCallSettings', path={'locationId': location_id, 'userId': user_id}, query={}, body=None)

    def update_user_after_call_settings(self, location_id: str, user_id: str, body: Mapping[str, Any]) -> Any:
        """Update a user's After Call settings. `PATCH /locations/{locationId}/users/{userId}/after-call-settings` (reseller_admin)."""
        return self._c._call('updateUserAfterCallSettings', path={'locationId': location_id, 'userId': user_id}, query={}, body=body)


class AccountAPI(Namespace):
    """Account operations."""

    def get_me(self) -> Any:
        """Who is signed in. `GET /me` (frontline_user)."""
        return self._c._call('getMe', path={}, query={}, body=None)

    def list_visible_locations(self, *, search: Optional[str] = None, is_active: Optional[bool] = None, company_id: Optional[str] = None, limit: Optional[int] = None, cursor: Optional[str] = None, offset: Optional[int] = None) -> Page:
        """Locations this login can see. `GET /locations` (frontline_user)."""
        return self._c._page('listVisibleLocations', path={}, query={'search': search, 'is_active': is_active, 'company_id': company_id, 'limit': limit, 'cursor': cursor, 'offset': offset}, body=None)

    def iter_visible_locations(self, *, search: Optional[str] = None, is_active: Optional[bool] = None, company_id: Optional[str] = None, offset: Optional[int] = None) -> Iterator[Any]:
        """Every item of `list_visible_locations`, following cursors 100 at a time."""
        return self._c._iter('listVisibleLocations', path={}, query={'search': search, 'is_active': is_active, 'company_id': company_id, 'offset': offset})


class CallsAPI(Namespace):
    """Calls operations."""

    def list_calls(self, *, date_from: Optional[Union[str, datetime]] = None, date_to: Optional[Union[str, datetime]] = None, status: Optional[str] = None, sentiment: Optional[str] = None, has_open_tasks: Optional[bool] = None, multi_leg: Optional[bool] = None, location_id: Optional[Union[str, Sequence[str]]] = None, company_id: Optional[str] = None, search: Optional[str] = None, cursor: Optional[str] = None, limit: Optional[int] = None) -> Page:
        """List calls. `GET /calls` (frontline_user)."""
        return self._c._page('listCalls', path={}, query={'date_from': date_from, 'date_to': date_to, 'status': status, 'sentiment': sentiment, 'has_open_tasks': has_open_tasks, 'multi_leg': multi_leg, 'location_id': location_id, 'company_id': company_id, 'search': search, 'cursor': cursor, 'limit': limit}, body=None)

    def iter_calls(self, *, date_from: Optional[Union[str, datetime]] = None, date_to: Optional[Union[str, datetime]] = None, status: Optional[str] = None, sentiment: Optional[str] = None, has_open_tasks: Optional[bool] = None, multi_leg: Optional[bool] = None, location_id: Optional[Union[str, Sequence[str]]] = None, company_id: Optional[str] = None, search: Optional[str] = None) -> Iterator[Any]:
        """Every item of `list_calls`, following cursors 100 at a time."""
        return self._c._iter('listCalls', path={}, query={'date_from': date_from, 'date_to': date_to, 'status': status, 'sentiment': sentiment, 'has_open_tasks': has_open_tasks, 'multi_leg': multi_leg, 'location_id': location_id, 'company_id': company_id, 'search': search})

    def get_call(self, call_id: str) -> Any:
        """Read a call. `GET /calls/{callId}` (frontline_user)."""
        return self._c._call('getCall', path={'callId': call_id}, query={}, body=None)

    def get_call_transcript(self, call_id: str) -> Any:
        """Read a call's transcript. `GET /calls/{callId}/transcript` (frontline_user)."""
        return self._c._call('getCallTranscript', path={'callId': call_id}, query={}, body=None)


class AlertsAPI(Namespace):
    """Alerts operations."""

    def list_alerts(self, *, date_from: Optional[Union[str, datetime]] = None, date_to: Optional[Union[str, datetime]] = None, keyword: Optional[str] = None, topic: Optional[str] = None, numbers: Optional[Union[str, Sequence[str]]] = None, sentiment: Optional[str] = None, search: Optional[str] = None, location_id: Optional[Union[str, Sequence[str]]] = None, company_id: Optional[str] = None, cursor: Optional[str] = None, limit: Optional[int] = None) -> Page:
        """List alerts. `GET /alerts` (frontline_user)."""
        return self._c._page('listAlerts', path={}, query={'date_from': date_from, 'date_to': date_to, 'keyword': keyword, 'topic': topic, 'numbers': numbers, 'sentiment': sentiment, 'search': search, 'location_id': location_id, 'company_id': company_id, 'cursor': cursor, 'limit': limit}, body=None)

    def iter_alerts(self, *, date_from: Optional[Union[str, datetime]] = None, date_to: Optional[Union[str, datetime]] = None, keyword: Optional[str] = None, topic: Optional[str] = None, numbers: Optional[Union[str, Sequence[str]]] = None, sentiment: Optional[str] = None, search: Optional[str] = None, location_id: Optional[Union[str, Sequence[str]]] = None, company_id: Optional[str] = None) -> Iterator[Any]:
        """Every item of `list_alerts`, following cursors 100 at a time."""
        return self._c._iter('listAlerts', path={}, query={'date_from': date_from, 'date_to': date_to, 'keyword': keyword, 'topic': topic, 'numbers': numbers, 'sentiment': sentiment, 'search': search, 'location_id': location_id, 'company_id': company_id})

    def get_alerts_dashboard(self, *, date_from: Optional[Union[str, datetime]] = None, date_to: Optional[Union[str, datetime]] = None, location_id: Optional[Union[str, Sequence[str]]] = None, company_id: Optional[str] = None) -> Any:
        """Alert totals. `GET /alerts/dashboard` (frontline_user)."""
        return self._c._call('getAlertsDashboard', path={}, query={'date_from': date_from, 'date_to': date_to, 'location_id': location_id, 'company_id': company_id}, body=None)


class TasksAPI(Namespace):
    """Tasks operations."""

    def list_tasks(self, *, status: Optional[str] = None, today_start: Optional[Union[str, datetime]] = None, call_id: Optional[str] = None, task_id: Optional[str] = None, due_on: Optional[Union[str, date]] = None, date_from: Optional[Union[str, datetime]] = None, date_to: Optional[Union[str, datetime]] = None, search: Optional[str] = None, location_id: Optional[Union[str, Sequence[str]]] = None, company_id: Optional[str] = None, cursor: Optional[str] = None, limit: Optional[int] = None) -> Page:
        """List tasks. `GET /tasks` (frontline_user)."""
        return self._c._page('listTasks', path={}, query={'status': status, 'today_start': today_start, 'call_id': call_id, 'task_id': task_id, 'due_on': due_on, 'date_from': date_from, 'date_to': date_to, 'search': search, 'location_id': location_id, 'company_id': company_id, 'cursor': cursor, 'limit': limit}, body=None)

    def iter_tasks(self, *, status: Optional[str] = None, today_start: Optional[Union[str, datetime]] = None, call_id: Optional[str] = None, task_id: Optional[str] = None, due_on: Optional[Union[str, date]] = None, date_from: Optional[Union[str, datetime]] = None, date_to: Optional[Union[str, datetime]] = None, search: Optional[str] = None, location_id: Optional[Union[str, Sequence[str]]] = None, company_id: Optional[str] = None) -> Iterator[Any]:
        """Every item of `list_tasks`, following cursors 100 at a time."""
        return self._c._iter('listTasks', path={}, query={'status': status, 'today_start': today_start, 'call_id': call_id, 'task_id': task_id, 'due_on': due_on, 'date_from': date_from, 'date_to': date_to, 'search': search, 'location_id': location_id, 'company_id': company_id})


class InsightsAPI(Namespace):
    """Insights operations."""

    def get_insights_dashboard(self, *, start: Union[str, datetime], end: Union[str, datetime], trending_limit: Optional[int] = None, location_id: Optional[Union[str, Sequence[str]]] = None, company_id: Optional[str] = None) -> Any:
        """Insights Hub dashboard. `GET /insights/dashboard` (frontline_user)."""
        return self._c._call('getInsightsDashboard', path={}, query={'start': start, 'end': end, 'trending_limit': trending_limit, 'location_id': location_id, 'company_id': company_id}, body=None)

    def list_topic_calls(self, slug: str, *, date_from: Optional[Union[str, datetime]] = None, date_to: Optional[Union[str, datetime]] = None, sentiment: Optional[str] = None, outcome: Optional[str] = None, search: Optional[str] = None, location_id: Optional[Union[str, Sequence[str]]] = None, company_id: Optional[str] = None, cursor: Optional[str] = None, limit: Optional[int] = None) -> Page:
        """Calls for one topic. `GET /insights/topics/{slug}/calls` (frontline_user)."""
        return self._c._page('listTopicCalls', path={'slug': slug}, query={'date_from': date_from, 'date_to': date_to, 'sentiment': sentiment, 'outcome': outcome, 'search': search, 'location_id': location_id, 'company_id': company_id, 'cursor': cursor, 'limit': limit}, body=None)

    def iter_topic_calls(self, slug: str, *, date_from: Optional[Union[str, datetime]] = None, date_to: Optional[Union[str, datetime]] = None, sentiment: Optional[str] = None, outcome: Optional[str] = None, search: Optional[str] = None, location_id: Optional[Union[str, Sequence[str]]] = None, company_id: Optional[str] = None) -> Iterator[Any]:
        """Every item of `list_topic_calls`, following cursors 100 at a time."""
        return self._c._iter('listTopicCalls', path={'slug': slug}, query={'date_from': date_from, 'date_to': date_to, 'sentiment': sentiment, 'outcome': outcome, 'search': search, 'location_id': location_id, 'company_id': company_id})


class WebhooksAPI(Namespace):
    """Events and webhooks operations."""

    def get_after_call_webhook(self, location_id: str) -> Any:
        """Read the After Call webhook. `GET /locations/{locationId}/after-call/automation` (reseller_admin)."""
        return self._c._call('getAfterCallWebhook', path={'locationId': location_id}, query={}, body=None)

    def save_after_call_webhook(self, location_id: str, body: Mapping[str, Any]) -> Any:
        """Set the After Call webhook. `PUT /locations/{locationId}/after-call/automation` (reseller_admin)."""
        return self._c._call('saveAfterCallWebhook', path={'locationId': location_id}, query={}, body=body)

    def test_after_call_webhook(self, location_id: str) -> Any:
        """Send a test After Call event. `POST /locations/{locationId}/after-call/automation/test` (reseller_admin)."""
        return self._c._call('testAfterCallWebhook', path={'locationId': location_id}, query={}, body=None)

