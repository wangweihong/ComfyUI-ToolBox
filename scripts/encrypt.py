#!/usr/bin/env python3
import argparse
import os
import json
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ROOT_DIR = Path(__file__).resolve().parents[1]

DEFAULT_INPUT = ROOT_DIR / "prompts"
DEFAULT_OUTPUT = ROOT_DIR / "encrypted"


SALT_SIZE = 16
NONCE_SIZE = 12


def derive_key(password: str, salt: bytes):
    """
    PBKDF2 derive AES key
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=600000,
    )

    return kdf.derive(password.encode())


def encrypt_file(src: Path, dst: Path, password: str):

    data = src.read_bytes()

    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)

    key = derive_key(password, salt)

    aes = AESGCM(key)

    encrypted = aes.encrypt(
        nonce,
        data,
        None
    )

    payload = {
        "salt": salt.hex(),
        "nonce": nonce.hex(),
        "data": encrypted.hex()
    }

    dst.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    dst.write_text(
        json.dumps(payload),
        encoding="utf-8"
    )


def decrypt_file(src: Path, dst: Path, password: str):

    payload = json.loads(
        src.read_text(
            encoding="utf-8"
        )
    )

    salt = bytes.fromhex(
        payload["salt"]
    )

    nonce = bytes.fromhex(
        payload["nonce"]
    )

    data = bytes.fromhex(
        payload["data"]
    )

    key = derive_key(password, salt)

    aes = AESGCM(key)

    decrypted = aes.decrypt(
        nonce,
        data,
        None
    )

    dst.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    dst.write_bytes(
        decrypted
    )


def encrypt_directory(
    input_dir: Path,
    output_dir: Path,
    password: str
):

    for file in input_dir.rglob("*"):

        if not file.is_file():
            continue

        relative = file.relative_to(input_dir)

        output = (
            output_dir /
            relative
        )

        output = output.with_suffix(
            output.suffix + ".enc"
        )

        print(
            f"Encrypt {file}"
        )

        encrypt_file(
            file,
            output,
            password
        )


def decrypt_directory(
    input_dir: Path,
    output_dir: Path,
    password: str
):

    for file in input_dir.rglob("*.enc"):

        relative = file.relative_to(input_dir)

        name = relative.name[:-4]

        output = (
            output_dir /
            relative.parent /
            name
        )

        print(
            f"Decrypt {file}"
        )

        decrypt_file(
            file,
            output,
            password
        )


def main():

    parser = argparse.ArgumentParser(
        description="Encrypt/decrypt prompts directory"
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True
    )

    enc = sub.add_parser(
        "encrypt"
    )

    dec = sub.add_parser(
        "decrypt"
    )


    for p in (enc, dec):

        p.add_argument(
            "--input",
            type=Path,
            default=DEFAULT_INPUT
        )

        p.add_argument(
            "--output",
            type=Path,
            default=DEFAULT_OUTPUT
        )

        p.add_argument(
            "--password",
            required=True
        )


    args = parser.parse_args()


    if args.command == "encrypt":

        encrypt_directory(
            args.input,
            args.output,
            args.password
        )

    else:

        decrypt_directory(
            args.input,
            args.output,
            args.password
        )


if __name__ == "__main__":
    main()