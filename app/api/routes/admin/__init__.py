"""The routes for the people who operate Baton, kept in their own package.

Not because there will be many of them, though there will, but because
every other route in this application is scoped to one workspace and
these are scoped to none. A file in `app/api/routes` is a tenant surface;
a file in here is not, and the directory is the thing that makes that
true at a glance rather than by reading imports.

The package is composed in `app/api/admin_router.py` and mounted by
`app/main.py` separately from `api_router`, so that no admin path can be
reached through the tenant router by an include somebody adds in a hurry.
"""
