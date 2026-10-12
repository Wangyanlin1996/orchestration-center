# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
import pytest
from unittest.mock import MagicMock, patch
from common.cert.cert_validator import (


    PathValidator, PathValidatorLink, CommonContentValidator,
    CerContentValidator, PrivateKeyValidator, CRLValidator,
    CerContentValidatorLink, CertValidator,
)

from common.util.validation_result import ValidationResult
from common.util.conf_obj import ConfObj


class TestPathValidator:

    def test_valid_path_returns_success(self, tmp_path):
        cer_file = tmp_path / "test.cer"
        cer_file.write_text("dummy")
        v = PathValidator(str(cer_file), suffix=".cer", is_required=True)
        result = v.validate()
        assert result.is_valid

    def test_empty_required_path_returns_failure(self):
        v = PathValidator("", suffix=".cer", is_required=True, conf_tip="ssl_certfile")
        result = v.validate()
        assert not result.is_valid
        assert "empty" in result.message.lower()

    def test_none_required_path_returns_failure(self):
        v = PathValidator(None, suffix=".cer", is_required=True)
        result = v.validate()
        assert not result.is_valid

    def test_empty_optional_path_returns_success(self):
        v = PathValidator("", suffix=".cer", is_required=False)
        result = v.validate()
        assert result.is_valid
        assert "Not config" in result.message

    def test_nonexistent_path_returns_failure(self):
        v = PathValidator("/nonexistent/path.cer", suffix=".cer", is_required=True)
        result = v.validate()
        assert not result.is_valid
        assert "does not exist" in result.message.lower()

    def test_wrong_extension_returns_failure(self, tmp_path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("dummy")
        v = PathValidator(str(txt_file), suffix=".cer", is_required=True)
        result = v.validate()
        assert not result.is_valid
        assert "not support" in result.message.lower()

    def test_empty_suffix_accepts_any_extension(self, tmp_path):
        cer_file = tmp_path / "test.any"
        cer_file.write_text("dummy")
        v = PathValidator(str(cer_file), suffix="", is_required=True)
        result = v.validate()
        assert result.is_valid

    def test_is_support_format_matches_suffix(self):
        v = PathValidator("", suffix=".cer", is_required=True)
        assert v.is_support_format(".cer")
        assert not v.is_support_format(".txt")

    def test_is_support_format_empty_suffix_accepts_all(self):
        v = PathValidator("", suffix="", is_required=True)
        assert v.is_support_format(".anything")


class TestCommonContentValidator:

    def test_validate_public_key_length_rsa_meets_threshold(self):

        from cryptography.hazmat.primitives.asymmetric import rsa


        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        assert CommonContentValidator.validate_public_key_length(key.public_key())

    def test_validate_public_key_length_rsa_below_threshold(self):

        from cryptography.hazmat.primitives.asymmetric import rsa


        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        assert not CommonContentValidator.validate_public_key_length(key.public_key())

    def test_validate_private_key_length_rsa_meets_threshold(self):

        from cryptography.hazmat.primitives.asymmetric import rsa


        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        assert CommonContentValidator.validate_private_key_length(key)

    def test_validate_private_key_length_rsa_below_threshold(self):

        from cryptography.hazmat.primitives.asymmetric import rsa


        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        assert not CommonContentValidator.validate_private_key_length(key)

    def test_validate_public_key_length_unknown_type_returns_false(self):
        assert not CommonContentValidator.validate_public_key_length("not_a_key")


class TestPrivateKeyValidatorPasswordVerify:

    def test_valid_password_meets_requirements(self):
        v = PrivateKeyValidator.__new__(PrivateKeyValidator)
        v.min_length = 8
        result = v.password_verify("Abc123!@")
        assert result

    def test_short_password_fails(self):
        v = PrivateKeyValidator.__new__(PrivateKeyValidator)
        v.min_length = 8
        result = v.password_verify("Ab1!")
        assert not result

    def test_password_with_only_digits_fails(self):
        v = PrivateKeyValidator.__new__(PrivateKeyValidator)
        v.min_length = 8
        result = v.password_verify("12345678")
        assert not result

    def test_password_with_two_types_passes(self):
        v = PrivateKeyValidator.__new__(PrivateKeyValidator)
        v.min_length = 8
        result = v.password_verify("abcd1234")
        assert result

    def test_password_with_upper_and_lower_passes(self):
        v = PrivateKeyValidator.__new__(PrivateKeyValidator)
        v.min_length = 8
        result = v.password_verify("Abcdefgh")
        assert result


class TestValidationResult:

    def test_valid_result(self):
        r = ValidationResult(True, "ok")
        assert r.is_valid
        assert r.message == "ok"

    def test_invalid_result(self):
        r = ValidationResult(False, "error msg")
        assert not r.is_valid
        assert r.message == "error msg"

    def test_str_representation(self):
        r = ValidationResult(True, "all good")
        s = str(r)
        assert "True" in s
        assert "all good" in s


class TestConfObj:

    def test_as_object_with_defaults(self):
        obj = ConfObj.as_object({})
        assert obj.ip == "127.0.0.1"
        assert obj.port == 5001

    def test_as_object_with_custom_values(self):
        obj = ConfObj.as_object({"ip": "0.0.0.0", "port": "8080"})
        assert obj.ip == "0.0.0.0"
        assert obj.port == 8080

    def test_as_object_port_string_converted_to_int(self):
        obj = ConfObj.as_object({"port": "9000"})
        assert obj.port == 9000
        assert isinstance(obj.port, int)

    def test_as_object_verify_client_false(self):
        obj = ConfObj.as_object({"verify_client": "false"})

        import ssl


        assert obj.verify_client == ssl.CERT_NONE

    def test_as_object_verify_client_default(self):

        import ssl


        obj = ConfObj.as_object({})
        assert obj.verify_client == ssl.CERT_REQUIRED

    def test_as_object_ssl_paths_are_absolute(self):
        obj = ConfObj.as_object({"ssl_certfile": "etc/ssl/server.cer"})
        assert not obj.ssl_certfile.startswith("etc/")

    def test_as_object_empty_crl_path_stays_empty(self):
        obj = ConfObj.as_object({"ssl_crl_file": ""})
        assert obj.ssl_crl_file == ""

    def test_as_object_missing_crl_key_defaults_to_empty(self):
        # Revocation checking is opt-in: an absent key must not invent a CRL
        # path that CertValidator would then demand on disk.
        obj = ConfObj.as_object({})
        assert obj.ssl_crl_file == ""

    def test_get_crl_list_empty_when_none(self):
        obj = ConfObj()
        obj.crl_list_data = None
        assert obj.get_crl_list() == []

    def test_get_crl_list_returns_serial_numbers(self):
        obj = ConfObj()
        mock_crl = MagicMock()
        mock_crl.serial_number = 123
        obj.crl_list_data = [mock_crl]
        result = obj.get_crl_list()
        assert len(result) == 1
        assert result[0] == hex(123)


class TestCipherConverter:

    def test_convert_known_iana_to_openssl(self):

        from common.util.cipher_converter import CipherConverter


        result = CipherConverter.convert("TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384")
        assert result == "ECDHE-RSA-AES256-GCM-SHA384"

    def test_convert_multiple_ciphers(self):

        from common.util.cipher_converter import CipherConverter


        iana = "TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384, TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256"
        result = CipherConverter.convert(iana)
        assert "ECDHE-RSA-AES256-GCM-SHA384" in result
        assert "ECDHE-ECDSA-AES128-GCM-SHA256" in result

    def test_auto_convert_unknown_cipher(self):

        from common.util.cipher_converter import CipherConverter


        result = CipherConverter.convert("TLS_UNKNOWN_CIPHER_WITH_AES")
        assert result != ""

    def test_skip_unrecognized_cipher(self):

        from common.util.cipher_converter import CipherConverter


        # UNKNOWN_CIPHER is not in IANA_TO_OPENSSL map and auto-convert
        # produces a non-empty result, so it gets included (not skipped)
        result = CipherConverter.convert("UNKNOWN_CIPHER")
        assert "UNKNOWN" in result

    def test_auto_convert_removes_tls_prefix(self):

        from common.util.cipher_converter import CipherConverter


        result = CipherConverter._auto_convert("TLS_ECDHE_RSA_WITH_AES_128_CBC")
        assert not result.startswith("TLS_")
