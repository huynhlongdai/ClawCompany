# Security Model

## Identities
- Human user: JWT
- Service/integration: API key
- AI employee: Member + Agent runtime binding

## Tenant boundary
`organization_id` is the top-level tenant scope. JWT and API-key principals carry one active organization scope.

## Roles
- guest
- member
- manager
- admin
- owner

## High-risk actions
Route through PermissionPolicy + Approval:
- payment / spend
- production deploy
- credential changes
- privileged agent provisioning
- destructive data actions
- public/customer publishing

## API keys
The raw key is returned once at creation; only a hash and prefix are persisted.
