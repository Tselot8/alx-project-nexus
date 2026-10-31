from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm
from django.db import transaction
from .models import User, UserProfile


class RevokingAdminPasswordChangeForm(AdminPasswordChangeForm):
    def save(self, commit=True):
        if not commit:
            return super().save(commit=False)
        from .v2_services import revoke_sessions

        with transaction.atomic():
            self.user = User.objects.select_for_update().get(pk=self.user.pk)
            user = super().save(commit=False)
            user.save(update_fields=["password"])
            revoke_sessions(user)
            return user


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    change_password_form = RevokingAdminPasswordChangeForm

    fieldsets = (
        (None, {'fields': ('email', 'username', 'password')}),
        ('Permissions', {'fields': ('is_staff', 'is_superuser', 'is_active')}),
        ('Dates', {'fields': ('date_joined',)}),
    )
    list_display = ('email', 'username', 'is_staff', 'is_active')
    search_fields = ('email', 'username')

    def save_model(self, request, obj, form, change):
        if not change:
            return super().save_model(request, obj, form, change)
        # Save only submitted fields, never a stale password or auth_version.
        fields = {
            field.name
            for field in obj._meta.concrete_fields
            if not field.primary_key
            and field.name not in {"auth_version", "password"}
        }
        changed = fields.intersection(form.changed_data)
        if changed:
            obj.save(update_fields=changed)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'location', 'last_seen')
