"""
Tests for the locking application
"""
import uuid

from freezegun import freeze_time

from django.core.management import call_command
from django.test import TestCase

from django.contrib.auth.models import User

from .exceptions import AlreadyLocked, RenewalError
from .models import NonBlockingLock, _get_lock_name


class NonBlockingLockTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='NonBlockingLock test')

    def test_acquire_and_release(self):
        ''' Tests an aquire/release cycle '''
        l = NonBlockingLock.objects.acquire_lock(self.user)
        self.assertTrue(NonBlockingLock.objects.is_locked(self.user))
        l.release()
        self.assertTrue(not NonBlockingLock.objects.is_locked(self.user))
        l2 = NonBlockingLock.objects.acquire_lock(self.user)
        self.assertTrue(NonBlockingLock.objects.is_locked(self.user))
        NonBlockingLock.objects.release_lock(l2.pk)
        self.assertTrue(not NonBlockingLock.objects.is_locked(self.user))

    def test_renew_integrity_error(self):
        l = NonBlockingLock.objects.acquire_lock(self.user)
        self.assertTrue(NonBlockingLock.objects.is_locked(self.user))
        NonBlockingLock.objects.release_lock(l.pk)
        self.assertFalse(NonBlockingLock.objects.is_locked(self.user))
        NonBlockingLock.objects.acquire_lock(self.user)
        self.assertTrue(NonBlockingLock.objects.is_locked(self.user))
        self.assertRaises(RenewalError, l.renew)

    def test_obj_with_expired_lock_is_not_locked(self):
        ''' Tests that manager.is_locked returns False if locks are expired '''
        with freeze_time("2015-01-01 10:00"):
            NonBlockingLock.objects.acquire_lock(self.user, max_age=1)
        with freeze_time("2015-01-01 11:00"):
            self.assertFalse(NonBlockingLock.objects.is_locked(self.user))

    def test_acquire_and_renew(self):
        ''' Tests an aquire/renew cycle '''
        with freeze_time("2015-01-01 10:00"):
            l = NonBlockingLock.objects.acquire_lock(self.user)
            expires = l.expires_on
        with freeze_time("2015-01-01 11:00"):
            l.renew()
            self.assertLess(expires, l.expires_on)

            l2 = NonBlockingLock.objects.renew_lock(l.pk)
            self.assertEqual(l.pk, l2.pk)
            self.assertEqual(l.expires_on, l2.expires_on)

    def test_lock_twice(self):
        ''' Tests a double locking (lock and try to lock again) '''
        l = NonBlockingLock.objects.acquire_lock(self.user)
        self.assertTrue(NonBlockingLock.objects.is_locked(self.user))
        self.assertRaises(AlreadyLocked, NonBlockingLock.objects.acquire_lock, self.user)
        self.assertTrue(NonBlockingLock.objects.is_locked(self.user))
        l.release()

    def test_unlock_twice(self):
        ''' Tests a double unlocking (unlock and try to unlock again) '''
        l = NonBlockingLock.objects.acquire_lock(self.user)
        self.assertTrue(NonBlockingLock.objects.is_locked(self.user))
        l.release()
        self.assertTrue(not NonBlockingLock.objects.is_locked(self.user))
        l.release()

    def test_model(self):
        '''Test the model'''
        l = NonBlockingLock.objects.acquire_lock(self.user, max_age=10)
        self.assertTrue(l.locked_object.endswith('%d' % self.user.id))
        self.assertEquals(l.locked_object, _get_lock_name(self.user))
        self.assertTrue(l.created_on)
        self.assertEquals(l.max_age, 10)
        l.release()
        l = NonBlockingLock.objects.acquire_lock(lock_name='test_lock', max_age=10)
        self.assertEquals(l.locked_object, 'test_lock')
        self.assertIsInstance(l.id, uuid.UUID)

    def test_unicode(self):
        ''' Test the __unicode__ '''
        l = NonBlockingLock.objects.acquire_lock(self.user)
        str_rep = '%s' % l
        self.assertNotEquals(str_rep.find('%d' % self.user.id), -1)
        l.release()

    def test_relock(self):
        '''Test to allow lock if lock is expired'''
        with freeze_time("2015-01-01 10:00"):
            l = NonBlockingLock.objects.acquire_lock(self.user, max_age=10)
        with freeze_time("2015-01-01 11:00"):
            self.assertTrue(l.is_expired)
            # try to lock again
            l2 = NonBlockingLock.objects.acquire_lock(self.user, max_age=1)
            self.assertNotEquals(l.created_on, l2.created_on)

    def test_expired(self):
        '''Test the expired locks'''
        with freeze_time("2015-01-01 10:00"):
            l = NonBlockingLock.objects.acquire_lock(self.user, max_age=0)
            l2 = NonBlockingLock.objects.acquire_lock(l, max_age=1)
        with freeze_time("2015-01-01 11:00"):
            self.assertTrue(not l.is_expired)
            self.assertTrue(l2.is_expired)
            expired_locks = NonBlockingLock.objects.get_expired_locks()
            self.assertEquals(len(expired_locks), 1)

    def test_context_manager(self):
        """A lock can be used as a context manager"""
        with NonBlockingLock.objects.acquire_lock(self.user):
            self.assertTrue(NonBlockingLock.objects.is_locked(self.user))
        self.assertFalse(NonBlockingLock.objects.is_locked(self.user))


class CleanExpiredLocksTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='CleanExpiredLocks test')

    def test_clean_locks(self):
        with freeze_time("2015-01-01 10:00"):
            NonBlockingLock.objects.acquire_lock(self.user, max_age=1)

        self.assertEqual(1, NonBlockingLock.objects.get_expired_locks().count())
        call_command('clean_expired_locks', dry_run=True)
        self.assertEqual(1, NonBlockingLock.objects.get_expired_locks().count())
        call_command('clean_expired_locks')
        self.assertEqual(0, NonBlockingLock.objects.get_expired_locks().count())
