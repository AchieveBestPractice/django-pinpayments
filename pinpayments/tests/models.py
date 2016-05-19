""" Ensure that the models work as intended """

from __future__ import absolute_import, unicode_literals

import json
from pinpayments.models import (
    ConfigError,
    CustomerToken,
    PinError,
    PinTransaction
, CardToken)
from pinpayments.utils import get_user_model

from django.conf import settings
from django.test import TestCase
from django.test.utils import override_settings
from mock import patch
from requests import Response
from six import binary_type


User = get_user_model()

ENV_MISSING_SECRET = {
    'test': {
        'key': 'key1',
        'host': 'test-api.pin.net.au',
    },
}

ENV_MISSING_HOST = {
    'test': {
        'key': 'key1',
        'secret': 'secret1',
    },
}


class FakeResponse(Response):
    def __init__(self, status_code, content):
        super(FakeResponse, self).__init__()
        self.status_code = status_code
        if type(content) != binary_type:
            content = binary_type(content, 'utf-8')
        self._content = content


class CustomerTokenTests(TestCase):
    # Need to override the setting so we can delete it, not sure why.
    @override_settings(PIN_DEFAULT_ENVIRONMENT=None)
    def test_default_environment(self):
        """
        Unset PIN_DEFAULT_ENVIRONMENT to test that the environment defaults
        to 'test'.
        """
        del settings.PIN_DEFAULT_ENVIRONMENT
        token = CustomerToken()
        token.user = User.objects.create()
        token.environment = None
        token.save()
        self.assertEqual(token.environment, 'test')


class CardTokenTests(TestCase):
    """ Test the creation of card tokens in various ways"""
    def setUp(self):
        """ Common setup for methods """
        super(CardTokenTests, self).setUp()
        self.user = User.objects.create()
        self.customer_card_token_dict = {
            'response': {
                'token': '1234',
                'email': 'test@example.com',
                'created_at': '2012-06-22T06:27:33Z',
                'card': {
                    'token': '54321',
                    'display_number': 'XXXX-XXXX-XXXX-0000',
                    'scheme': 'master',
                    'expiry_month': 6,
                    'expiry_year': 2017,
                    'name': 'Roland Robot',
                    'address_line1': '42 Sevenoaks St',
                    'address_line2': None,
                    'address_city': 'Lathlain',
                    'address_postcode': '6454',
                    'address_state': 'WA',
                    'address_country': 'Australia',
                    'primary': True,
                }
            }
        }
        # customer token and first card token response
        self.customer_token_data = json.dumps(self.customer_card_token_dict)

        # add second card token response
        self.customer_card_token_2_dict = {'response': self.customer_card_token_dict['response']['card'].copy()}
        self.customer_card_token_2_dict['response']['primary'] = False
        self.customer_card_token_2_dict['response']['token'] = '987654321'
        self.customer_card_token_2_dict['response']['display_number'] = 'XXXX-XXXX-XXXX-4321'
        self.customer_card_token_2_data = json.dumps(self.customer_card_token_2_dict)

        # change primary card token response
        self.customer_put_card_token_dict = self.customer_card_token_dict.copy()  # grab initial cust response
        self.customer_put_card_token_dict['response']['card'] = self.customer_card_token_dict['response'].copy()  # swap the 2nd card in
        self.customer_put_card_token_dict['response']['card']['primary'] = True  # set to primary

        self.customer_put_update_card_token_data = json.dumps(self.customer_put_card_token_dict)

        self.response_error = json.dumps({
            'error': 'invalid_resource',
            'error_description':
                'One or more parameters were missing or invalid.'
        })

    @patch('requests.post')
    def test_primary_true(self, mock_request):
        """ Validate successful response """
        mock_request.return_value = FakeResponse(200, self.customer_token_data)
        customer = CustomerToken.objects.create_from_card_token(
            '1234', self.user, environment='test'
        )

        self.assertIsInstance(customer, CustomerToken)
        self.assertEqual(customer.user, self.user)
        self.assertEqual(customer.token, '1234')
        self.assertEqual(customer.environment, 'test')
        self.assertEqual(customer.primary_card.display_number, 'XXXX-XXXX-XXXX-0000')
        self.assertEqual(customer.primary_card.scheme, 'master')
        return customer

    @patch('requests.put')
    @patch('requests.post')
    def test_multiple_cards(self, mock_request_post, mock_request_put):
        """ Test mutiple cards """
        mock_request_post.return_value = FakeResponse(200, self.customer_token_data)
        customer = CustomerToken.objects.create_from_card_token(
            '1234', self.user, environment='test'
        )

        mock_request_post.return_value = FakeResponse(200, self.customer_card_token_2_data)
        card2 = customer.add_card_token('987654321')

        self.assertIsInstance(card2, CardToken)

        # cards test created
        self.assertNotEqual(customer.primary_card, card2)
        self.assertEqual(customer.cards.count(), 2)

        # additional card value tests
        self.assertEqual(card2.token, '987654321')
        self.assertEqual(card2.display_number, 'XXXX-XXXX-XXXX-4321')
        self.assertEqual(card2.scheme, 'master')

        # customer value tests
        self.assertEqual(customer.token, '1234')
        self.assertEqual(customer.environment, 'test')
        self.assertEqual(customer.primary_card.token, '54321')
        self.assertEqual(customer.primary_card.display_number, 'XXXX-XXXX-XXXX-0000')
        self.assertEqual(customer.primary_card.scheme, 'master')

        # change primary card
        mock_request_put.return_value = FakeResponse(200, self.customer_put_update_card_token_data)
        old_primary_card = customer.primary_card
        customer.set_primary_card(card2)

        # changed primary card tests
        old_primary_card = CardToken.objects.get(pk=old_primary_card.pk)
        self.assertEqual(customer.primary_card, card2)
        self.assertEqual(customer.cards.count(), 2)
        self.assertEqual(old_primary_card.primary, False)


class CreateFromCardTokenTests(TestCase):
    """ Test the creation of customer tokens from card tokens """
    def setUp(self):
        """ Common setup for methods """
        super(CreateFromCardTokenTests, self).setUp()
        self.user = User.objects.create()
        self.response_data = json.dumps({
            'response': {
                'token': '1234',
                'email': 'test@example.com',
                'created_at': '2012-06-22T06:27:33Z',
                'card': {
                    'token': '54321',
                    'display_number': 'XXXX-XXXX-XXXX-0000',
                    'scheme': 'master',
                    'expiry_month': 6,
                    'expiry_year': 2017,
                    'name': 'Roland Robot',
                    'address_line1': '42 Sevenoaks St',
                    'address_line2': None,
                    'address_city': 'Lathlain',
                    'address_postcode': '6454',
                    'address_state': 'WA',
                    'address_country': 'Australia',
                    'primary': None,
                }
            }
        })
        self.response_error = json.dumps({
            'error': 'invalid_resource',
            'error_description':
                'One or more parameters were missing or invalid.'
        })

    @patch('requests.post')
    def test_default_environment(self, mock_request):
        """ return a default environment """
        mock_request.return_value = FakeResponse(200, self.response_data)
        token = CustomerToken.create_from_card_token('1234', self.user)
        self.assertEqual(token.environment, 'test')

    @override_settings(PIN_ENVIRONMENTS={})
    @patch('requests.post')
    def test_valid_environment(self, mock_request):
        """ Check errors are raised with no environments """
        mock_request.return_value = FakeResponse(200, self.response_data)
        with self.assertRaises(ConfigError):
            CustomerToken.create_from_card_token(
                '1234', self.user, environment='test'
            )

    @override_settings(PIN_ENVIRONMENTS=ENV_MISSING_SECRET)
    @patch('requests.post')
    def test_secret_set(self, mock_request):
        """ Check errors are raised when the secret is not set """
        mock_request.return_value = FakeResponse(200, self.response_data)
        with self.assertRaises(ConfigError):
            CustomerToken.create_from_card_token(
                '1234', self.user, environment='test'
            )

    @override_settings(PIN_ENVIRONMENTS=ENV_MISSING_HOST)
    @patch('requests.post')
    def test_host_set(self, mock_request):
        """ Check errors are raised when the host is not set """
        mock_request.return_value = FakeResponse(200, self.response_data)
        with self.assertRaises(ConfigError):
            CustomerToken.create_from_card_token(
                '1234', self.user, environment='test'
            )

    @patch('requests.post')
    def test_response_not_json(self, mock_request):
        """ Validate non-json response """
        mock_request.return_value = FakeResponse(200, '')
        with self.assertRaises(PinError):
            CustomerToken.create_from_card_token(
                '1234', self.user, environment='test'
            )

    @patch('requests.post')
    def test_response_error(self, mock_request):
        """ Validate generic error response """
        mock_request.return_value = FakeResponse(200, self.response_error)
        with self.assertRaises(PinError):
            CustomerToken.create_from_card_token(
                '1234', self.user, environment='test'
            )

    @patch('requests.post')
    def test_response_success(self, mock_request):
        """ Validate successful response """
        mock_request.return_value = FakeResponse(200, self.response_data)
        customer = CustomerToken.create_from_card_token(
            '1234', self.user, environment='test'
        )
        self.assertIsInstance(customer, CustomerToken)
        self.assertEqual(customer.user, self.user)
        self.assertEqual(customer.token, '1234')
        self.assertEqual(customer.environment, 'test')
        self.assertEqual(customer.cards.all()[0].display_number, 'XXXX-XXXX-XXXX-0000')
        self.assertEqual(customer.cards.all()[0].scheme, 'master')


class PinTransactionTests(TestCase):
    """ Transaction construction/init related tests """
    def setUp(self):
        """ Common setup for methods """
        super(PinTransactionTests, self).setUp()
        self.transaction = PinTransaction()
        self.transaction.card_token = '12345'
        self.transaction.ip_address = '127.0.0.1'
        self.transaction.amount = 500
        self.transaction.currency = 'AUD'
        self.transaction.email_address = 'test@example.com'
        self.transaction.environment = 'test'

    # Need to override the setting so we can delete it, not sure why.
    @override_settings(PIN_DEFAULT_ENVIRONMENT=None)
    def test_save_defaults(self):
        """
        Unset PIN_DEFAULT_ENVIRONMENT to test that the environment defaults
        to 'test'.
        """
        del settings.PIN_DEFAULT_ENVIRONMENT
        self.transaction.environment = None
        self.transaction.save()
        self.assertEqual(self.transaction.environment, 'test')
        self.assertTrue(self.transaction.date)

    def test_save_notokens(self):
        """
        Check that an error is thrown if neither card nor customer token
        are provided to the transaction
        """
        self.transaction.card_token = None
        self.transaction.customer_token = None
        self.assertRaises(PinError, self.transaction.save)

    def test_valid_environment(self):
        """
        Check that errors are thrown when a fake environment is requested
        """
        self.transaction.environment = 'this should not exist'
        self.assertRaises(PinError, self.transaction.save)


class ProcessTransactionsTests(TestCase):
    """ Transaction processing related tests """
    def setUp(self):
        """ Common setup for methods """
        super(ProcessTransactionsTests, self).setUp()
        self.transaction = PinTransaction()
        self.transaction.card_token = '12345'
        self.transaction.ip_address = '127.0.0.1'
        self.transaction.amount = 500
        self.transaction.currency = 'AUD'
        self.transaction.email_address = 'test@example.com'
        self.transaction.environment = 'test'
        self.transaction.save()
        self.response_data = json.dumps({
            'response': {
                'token': '12345',
                'success': True,
                'amount': 500,
                'total_fees': 500,
                'currency': 'AUD',
                'description': 'test charge',
                'email': 'test@example.com',
                'ip_address': '127.0.0.1',
                'created_at': '2012-06-20T03:10:49Z',
                'status_message': 'Success!',
                'error_message': None,
                'card': {
                    'token': 'card_nytGw7koRg23EEp9NTmz9w',
                    'display_number': 'XXXX-XXXX-XXXX-0000',
                    'scheme': 'master',
                    'expiry_month': 6,
                    'expiry_year': 2017,
                    'name': 'Roland Robot',
                    'address_line1': '42 Sevenoaks St',
                    'address_line2': None,
                    'address_city': 'Lathlain',
                    'address_postcode': '6454',
                    'address_state': 'WA',
                    'address_country': 'Australia',
                    'primary': None,
                },
                'transfer': None
            }
        })
        self.response_error = json.dumps({
            'error': 'invalid_resource',
            'error_description':
                'One or more parameters were missing or invalid.',
            # Should there really be a charge token?
            'charge_token': '1234',
            'messages': [{
                'code': 'description_invalid',
                'message': 'Description can\'t be blank',
                'param': 'description'
            }]
        })
        self.response_error_no_messages = json.dumps({
            'error': 'invalid_resource',
            'error_description':
                'One or more parameters were missing or invalid.',
            # Should there really be a charge token?
            'charge_token': '1234'
        })

    @patch('requests.post')
    def test_only_process_once(self, mock_request):
        """ Check that transactions are processed exactly once """
        mock_request.return_value = FakeResponse(200, self.response_data)

        # Shouldn't be marked as processed before process_transaction is called
        # for the first time.
        self.assertFalse(self.transaction.processed)

        # Should be marked after the first call.
        result = self.transaction.process_transaction()
        self.assertTrue(self.transaction.processed)

        # Shouldn't process anything the second time
        result = self.transaction.process_transaction()
        self.assertIsNone(result)

    @override_settings(PIN_ENVIRONMENTS={})
    @patch('requests.post')
    def test_valid_environment(self, mock_request):
        """ Check that an error is thrown with no environment """
        mock_request.return_value = FakeResponse(200, self.response_data)
        self.assertRaises(PinError, self.transaction.process_transaction)

    @override_settings(PIN_ENVIRONMENTS=ENV_MISSING_SECRET)
    @patch('requests.post')
    def test_secret_set(self, mock_request):
        """ Check that an error is thrown with no secret """
        mock_request.return_value = FakeResponse(200, self.response_data)
        self.assertRaises(ConfigError, self.transaction.process_transaction)

    @override_settings(PIN_ENVIRONMENTS=ENV_MISSING_HOST)
    @patch('requests.post')
    def test_host_set(self, mock_request):
        """ Check that an error is thrown with no host """
        mock_request.return_value = FakeResponse(200, self.response_data)
        self.assertRaises(ConfigError, self.transaction.process_transaction)

    @patch('requests.post')
    def test_response_not_json(self, mock_request):
        """ Check that failure is returned for non-JSON responses """
        mock_request.return_value = FakeResponse(200, '')
        response = self.transaction.process_transaction()
        self.assertEqual(response, 'Failure.')

    @patch('requests.post')
    def test_response_badparam(self, mock_request):
        """ Check that a specific error is thrown for invalid parameters """
        mock_request.return_value = FakeResponse(200, self.response_error)
        response = self.transaction.process_transaction()
        self.assertEqual(response, 'Failure: Description can\'t be blank')

    @patch('requests.post')
    def test_response_noparam(self, mock_request):
        """ Check that a specific error is thrown for missing parameters """
        mock_request.return_value = FakeResponse(
            200, self.response_error_no_messages
        )
        response = self.transaction.process_transaction()
        self.assertEqual(
            response,
            'Failure: One or more parameters were missing or invalid.'
        )

    @patch('requests.post')
    def test_response_success(self, mock_request):
        """ Check that the success response is correctly processed """
        mock_request.return_value = FakeResponse(200, self.response_data)
        response = self.transaction.process_transaction()
        self.assertEqual(response, 'Success!')
        self.assertTrue(self.transaction.succeeded)
        self.assertEqual(self.transaction.transaction_token, '12345')
        self.assertEqual(self.transaction.fees, 5.0)
        self.assertEqual(self.transaction.pin_response, 'Success!')
        self.assertEqual(self.transaction.card_address1, '42 Sevenoaks St')
        self.assertIsNone(self.transaction.card_address2)
        self.assertEqual(self.transaction.card_city, 'Lathlain')
        self.assertEqual(self.transaction.card_state, 'WA')
        self.assertEqual(self.transaction.card_postcode, '6454')
        self.assertEqual(self.transaction.card_country, 'Australia')
        self.assertEqual(self.transaction.card_number, 'XXXX-XXXX-XXXX-0000')
        self.assertEqual(self.transaction.card_type, 'master')
