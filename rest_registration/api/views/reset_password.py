from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import Http404
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.generics import get_object_or_404

from rest_registration.decorators import api_view_serializer_class
from rest_registration.exceptions import BadRequest
from rest_registration.notifications import send_verification
from rest_registration.settings import registration_settings
from rest_registration.utils import (
    get_ok_response,
    get_user_setting,
    verify_signer_or_bad_request
)
from rest_registration.verification import URLParamsSigner


class ResetPasswordSigner(URLParamsSigner):
    salt = 'reset-password'
    use_timestamp = True

    @property
    def base_url(self):
        return registration_settings.RESET_PASSWORD_VERIFICATION_URL

    @property
    def valid_period(self):
        return registration_settings.RESET_PASSWORD_VERIFICATION_PERIOD


class SendResetPasswordLinkSerializer(serializers.Serializer):
    login = serializers.CharField(required=True)


def get_login_fields():
    user_class = get_user_model()
    return get_user_setting('LOGIN_FIELDS') or [user_class.USERNAME_FIELD]


@api_view_serializer_class(SendResetPasswordLinkSerializer)
@api_view(['POST'])
def send_reset_password_link(request):
    '''
    Send email with reset password link.
    '''
    serializer = SendResetPasswordLinkSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    login = serializer.data['login']
    user_class = get_user_model()
    user_queryset = user_class.objects.all()

    user = None
    for login_field in get_login_fields():
        try:
            user = get_object_or_404(user_queryset, **{login_field: login})
            break
        except Http404:
            pass

    if not user:
        raise BadRequest('User not found')

    signer = ResetPasswordSigner({
        'user_id': user.pk,
    }, request=request)

    template_config = (
        registration_settings.RESET_PASSWORD_VERIFICATION_EMAIL_TEMPLATES)
    send_verification(user, signer, template_config)

    return get_ok_response('Reset link sent')


class ResetPasswordSerializer(serializers.Serializer):
    user_id = serializers.CharField(required=True)
    timestamp = serializers.IntegerField(required=True)
    signature = serializers.CharField(required=True)
    password = serializers.CharField(required=True)


@api_view_serializer_class(ResetPasswordSerializer)
@api_view(['POST'])
def reset_password(request):
    '''
    Reset password, given the signature and timestamp from the link.
    '''
    process_reset_password_data(request.data)
    return get_ok_response('Reset password successful')


def process_reset_password_data(input_data):
    serializer = ResetPasswordSerializer(data=input_data)
    serializer.is_valid(raise_exception=True)

    data = serializer.data.copy()
    password = data.pop('password')
    signer = ResetPasswordSigner(data)
    verify_signer_or_bad_request(signer)

    user_class = get_user_model()
    user = get_object_or_404(user_class.objects.all(), pk=data['user_id'])
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        raise serializers.ValidationError(exc.messages[0])
    user.set_password(password)
    user.save()
