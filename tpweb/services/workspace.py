from django.contrib.auth import get_user_model


PUBLIC_WORKSPACE_USERNAME = "public"


def workspace_slug_for_user(user):
    if getattr(user, "is_authenticated", False) and getattr(user, "pk", None):
        return f"user-{user.pk}"
    return PUBLIC_WORKSPACE_USERNAME


def get_public_workspace_user():
    user_model = get_user_model()
    public_user, created = user_model.objects.get_or_create(
        username=PUBLIC_WORKSPACE_USERNAME,
        defaults={
            "name": "Public workspace",
            "is_active": True,
        },
    )
    if created:
        public_user.set_unusable_password()
        public_user.save(update_fields=["password"])
    return public_user


def resolve_workspace_user(user):
    if getattr(user, "is_authenticated", False):
        return user
    return get_public_workspace_user()


def session_key_for_user(user, key):
    return f"workspace:{workspace_slug_for_user(user)}:{key}"


def get_workspace_session_value(session, user, key, default=None):
    return session.get(session_key_for_user(user, key), default)


def set_workspace_session_value(session, user, key, value):
    session[session_key_for_user(user, key)] = value


def pop_workspace_session_value(session, user, key, default=None):
    return session.pop(session_key_for_user(user, key), default)
