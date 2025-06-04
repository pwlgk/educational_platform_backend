# users/tests.py

from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase 
from datetime import timedelta
import uuid
from unittest.mock import patch, MagicMock, AsyncMock 

from .models import Profile, InvitationCode

User = get_user_model()

class UserTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.test_user = User.objects.create_user(
            email='testuser@example.com',
            password='StrongPassword123!', # Изменен пароль
            first_name='Test',
            last_name='User',
            role=User.Role.STUDENT
        )
        cls.admin_user = User.objects.create_superuser(
            email='admin@example.com',
            password='AdminStrongPassword123!', # Изменен пароль
            first_name='Admin',
            last_name='User'
        )

    def test_create_user(self):
        user = User.objects.create_user(
            email='normaluser@example.com',
            password='UserStrongPassword123!', # Изменен пароль
            first_name='Normal',
            last_name='User',
            role=User.Role.TEACHER
        )
        self.assertEqual(user.email, 'normaluser@example.com')
        self.assertTrue(user.check_password('UserStrongPassword123!'))
        self.assertEqual(user.role, User.Role.TEACHER)
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertIsNotNone(user.confirmation_token)
        self.assertTrue(Profile.objects.filter(user=user).exists())
        profile = Profile.objects.get(user=user)
        self.assertEqual(profile.user, user)

    def test_create_user_without_email(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email='', password='password123')

    def test_create_superuser(self):
        admin_user = User.objects.create_superuser(
            email='super@example.com',
            password='SuperStrongPassword123!', # Изменен пароль
            first_name='Super',
            last_name='User'
        )
        self.assertEqual(admin_user.email, 'super@example.com')
        self.assertTrue(admin_user.check_password('SuperStrongPassword123!'))
        self.assertTrue(admin_user.is_staff)
        self.assertTrue(admin_user.is_superuser)
        self.assertTrue(admin_user.is_active)
        self.assertEqual(admin_user.role, User.Role.ADMIN)
        self.assertTrue(admin_user.is_role_confirmed)
        self.assertIsNotNone(admin_user.confirmation_token)
        self.assertTrue(Profile.objects.filter(user=admin_user).exists())

    def test_user_str_representation(self):
        self.assertEqual(str(self.test_user), self.test_user.email)

    def test_user_get_full_name(self):
        self.assertEqual(self.test_user.get_full_name(), 'Test User')
        user_no_name = User.objects.create_user(email='noname@example.com', password='passwordnoname1!')
        self.assertEqual(user_no_name.get_full_name(), 'noname@example.com')

    def test_user_get_short_name(self):
        self.assertEqual(self.test_user.get_short_name(), 'Test')
        user_no_firstname = User.objects.create_user(email='nofirst@example.com', password='passwordnofirst1!', last_name='OnlyLast')
        self.assertEqual(user_no_firstname.get_short_name(), 'nofirst')

    def test_user_role_properties(self):
        student = User.objects.create_user(email='student@example.com', password='pw', role=User.Role.STUDENT)
        teacher = User.objects.create_user(email='teacher@example.com', password='pw', role=User.Role.TEACHER)
        parent = User.objects.create_user(email='parent@example.com', password='pw', role=User.Role.PARENT)
        admin = User.objects.create_user(email='anotheradmin@example.com', password='pw', role=User.Role.ADMIN)

        self.assertTrue(student.is_student)
        self.assertFalse(student.is_teacher)
        self.assertTrue(teacher.is_teacher)
        self.assertFalse(teacher.is_admin)
        self.assertTrue(parent.is_parent)
        self.assertTrue(admin.is_admin)

    def test_parent_child_relationship(self):
        student = self.test_user
        parent1 = User.objects.create_user(email='parent1@example.com', password='pw', role=User.Role.PARENT, is_active=True, is_role_confirmed=True)
        parent2 = User.objects.create_user(email='parent2@example.com', password='pw', role=User.Role.PARENT, is_active=True, is_role_confirmed=True)
        
        student.parents.add(parent1, parent2)
        self.assertEqual(student.parents.count(), 2)
        self.assertIn(parent1, student.parents.all())
        self.assertIn(parent2, student.parents.all())
        self.assertIn(student, parent1.children.all())
        self.assertEqual(parent2.children.count(), 1)

class ProfileTests(APITestCase):
    def test_profile_creation_on_user_create(self):
        user = User.objects.create_user(email='profiletest@example.com', password='TestPassword123!')
        self.assertTrue(hasattr(user, 'profile'))
        self.assertIsInstance(user.profile, Profile)

    def test_profile_str_representation(self):
        user = User.objects.create_user(email='profileowner@example.com', password='TestPassword123!')
        profile = user.profile
        self.assertEqual(str(profile), f"Профиль {user.email}")

class InvitationCodeTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.creator = User.objects.create_user(email='creator@example.com', password='TestPassword123!', role=User.Role.TEACHER, is_active=True, is_role_confirmed=True)
        cls.student_user = User.objects.create_user(email='student_for_invite@example.com', password='TestPassword123!', role=User.Role.STUDENT)

    def test_invitation_code_creation_and_validity(self):
        code = InvitationCode.objects.create(created_by=self.creator, role=User.Role.STUDENT)
        self.assertIsNotNone(code.code)
        self.assertEqual(code.role, User.Role.STUDENT)
        self.assertTrue(code.is_valid())

    def test_invitation_code_usage(self):
        code = InvitationCode.objects.create(created_by=self.creator, role=User.Role.STUDENT)
        self.assertTrue(code.is_valid())
        code.used_by = self.student_user
        code.save()
        self.assertFalse(code.is_valid())

    def test_invitation_code_expiration(self):
        expired_time = timezone.now() - timedelta(days=1)
        code = InvitationCode.objects.create(created_by=self.creator, role=User.Role.STUDENT, expires_at=expired_time)
        self.assertFalse(code.is_valid())
        valid_time = timezone.now() + timedelta(days=1)
        valid_code = InvitationCode.objects.create(created_by=self.creator, role=User.Role.STUDENT, expires_at=valid_time)
        self.assertTrue(valid_code.is_valid())

class UserRegistrationAPITests(APITestCase):
    def test_user_registration_success(self):
        url = reverse('register')
        data = {
            'email': 'newuser@example.com',
            'password': 'ComplexPassword123!', # Изменен пароль
            'password2': 'ComplexPassword123!',
            'first_name': 'New', 'last_name': 'User', 'role': User.Role.STUDENT
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email='newuser@example.com').exists())
        user = User.objects.get(email='newuser@example.com')
        self.assertFalse(user.is_active)
        self.assertIn('message', response.data)
        self.assertIn('user', response.data)
        self.assertEqual(response.data['user']['email'], 'newuser@example.com')

    def test_user_registration_password_mismatch(self):
        url = reverse('register')
        data = {
            'email': 'mismatch@example.com',
            'password': 'ComplexSecurePassword1!',
            'password2': 'AnotherSecurePassword2@',
            'first_name': 'Mismatch', 'last_name': 'Pass', 'role': User.Role.STUDENT
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password2', response.data)

    def test_user_registration_existing_email(self):
        User.objects.create_user(email='exists@example.com', password='TestPassword123!')
        url = reverse('register')
        data = {
            'email': 'exists@example.com',
            'password': 'ComplexPassword123!',
            'password2': 'ComplexPassword123!',
            'first_name': 'Exists', 'last_name': 'Email', 'role': User.Role.STUDENT
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data)

    def test_user_registration_with_valid_invite_code(self):
        creator = User.objects.create_user(email='invite_creator@example.com', password='TestPassword123!', role=User.Role.TEACHER, is_active=True)
        invite_code = InvitationCode.objects.create(created_by=creator, role=User.Role.STUDENT)
        url = reverse('register')
        data = {
            'email': 'inviteduser@example.com',
            'password': 'InvitedUserSecurePass1#',
            'password2': 'InvitedUserSecurePass1#',
            'first_name': 'Invited', 'last_name': 'User', 'role': User.Role.STUDENT,
            'invite_code': invite_code.code
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='inviteduser@example.com')
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_role_confirmed)
        self.assertTrue(response.data['user']['used_invitation_code'])
        updated_invite_code = InvitationCode.objects.get(pk=invite_code.pk)
        self.assertEqual(updated_invite_code.used_by, user)

    def test_user_registration_with_invalid_invite_code(self):
        url = reverse('register')
        data = {
            'email': 'invalidinvite@example.com',
            'password': 'SecurePasswordForInviteTest1!',
            'password2': 'SecurePasswordForInviteTest1!',
            'first_name': 'Invalid', 'last_name': 'Invite', 'role': User.Role.STUDENT,
            'invite_code': 'nonexistentcode'
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('invite_code', response.data)

class ConfirmEmailAPITests(APITestCase):
    def test_confirm_email_success(self):
        token = uuid.uuid4()
        user_to_confirm = User.objects.create_user(
            email='confirmme@example.com', password='pw', role=User.Role.STUDENT,
            confirmation_token=token,
            confirmation_token_expires_at=timezone.now() + timedelta(days=1),
            is_active=False, is_role_confirmed=False
        )
        url = reverse('confirm-email', kwargs={'token': token})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user_to_confirm.refresh_from_db()
        self.assertTrue(user_to_confirm.is_active)
        self.assertTrue(user_to_confirm.is_role_confirmed)
        self.assertIsNone(user_to_confirm.confirmation_token)

    def test_confirm_email_invalid_token(self):
        invalid_token = uuid.uuid4()
        url = reverse('confirm-email', kwargs={'token': invalid_token})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_confirm_email_expired_token(self):
        token = uuid.uuid4()
        user_expired = User.objects.create_user(
            email='expiredtoken@example.com', password='pw',
            confirmation_token=token,
            confirmation_token_expires_at=timezone.now() - timedelta(days=1),
            is_active=False
        )
        url = reverse('confirm-email', kwargs={'token': token})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)
        self.assertIn("Срок действия токена", response.data['error'])
        user_expired.refresh_from_db()
        self.assertFalse(user_expired.is_active)

class UserProfileAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email='profileapi@example.com', password='TestPassword123!', first_name='Profile', last_name='API', is_active=True, is_role_confirmed=True)
        cls.url = reverse('user-profile')

    def test_get_profile_authenticated(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], self.user.email)
        self.assertIn('profile', response.data)

    def test_get_profile_unauthenticated(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_update_profile_patch(self):
        self.client.force_authenticate(user=self.user)
        update_data = {'first_name': 'UpdatedFirst', 'bio': 'This is my updated bio.'}
        response = self.client.patch(self.url, update_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.first_name, 'UpdatedFirst')
        self.assertEqual(self.user.profile.bio, 'This is my updated bio.')