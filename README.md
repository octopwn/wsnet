# WSNet Implementation in Python
This is the reference implementation of the WSNET proxy, all updates in functionality will be first implemented here before getting introduced to other languages.
This project, referred to as the "proxy" in the documentation, is designed to provide the necessary WebSocket-to-TCP translation required for the tools running inside of OctoPwn. This enables network communication between various components.

## How It Works
Upon starting the application, a WebSocket server is set up on `localhost` at port `8700`. The server then waits for a connection from OctoPwn to facilitate the required communication.

## Features
- **WebSocket-to-TCP translation**: Facilitates communication between OctoPwn and other networked components.
- **Websocket-to-UDP translation**: Facilitates communication between OctoPwn and other networked components.
- **Local File Browser**: Allows remote file operations from the browser to the system the proxy runs on.

## Support Matrix

| Feature                 | Windows | Linux | Mac |
|-------------------------|---------|-------|-----|
| TCP Client              | ✔       | ✔     | ✔   |
| TCP Server              | ✔       | ✔     | ✔   |
| UDP Client              | ✔       | ✔     | ✔   |
| UDP Server              | ✘       | ✘     | ✘   |
| Local File Browser      | ✔       | ✔     | ✔   |
| Authentication Proxy    | ✘       | ✘     | ✘   |

## Getting Started
### Prerequisites
- Python version 3.9 or later
- [OctoPwn](https://live.octopwn.com) set up and running

## Install
Either use PIP `pip install wsnet` or clone + install via GitHub.

### Command-Line Options

The following command-line options are available:

### Command Line Parameters

The `WSNET proxy server` script accepts several command line parameters that control its behavior. Below is a description of each parameter:

- `--ip`: Specifies the IP address the server will listen on. If not provided, the default is `127.0.0.1`.
  - **Example:** `--ip 192.168.1.100`

- `--port`: Specifies the port number the server will listen on. This must be an integer value. If not provided, the default is `8700`.
  - **Example:** `--port 8080`

- `-v`, `--verbose`: Increases the verbosity of the server's output. This option can be used multiple times to further increase verbosity. The default is `0` (no verbosity).
  - **Example:** `-v` or `-vv` for higher verbosity levels

- `--ssl-cert`: Specifies the path to the SSL certificate file. This is used to enable SSL/TLS for secure connections.
  - **Example:** `--ssl-cert /path/to/cert.pem`

- `--ssl-key`: Specifies the path to the SSL key file, which is paired with the SSL certificate.
  - **Example:** `--ssl-key /path/to/key.pem`

- `--ssl-ca`: Specifies the path to the CA (Certificate Authority) certificate file. This is used for validating client certificates in a mutual TLS setup.
  - **Example:** `--ssl-ca /path/to/ca.pem`

- `--secret`: Provides a secret string to protect the proxy server from malicious connections. Only clients that know the secret can connect.
  - **Example:** `--secret "mySecretString"`

- `--noorigin`: Disables origin header validation. This can be used when the origin of requests doesn't need to be validated.
  - **Example:** `--noorigin`

- `--disable-security`: Disables all security validations, effectively turning off SSL/TLS and other security checks. Use with caution.
  - **Example:** `--disable-security`

- `--plaintext`: Disables TLS (SSL) and allows connections over plain text. This option should be used carefully as it exposes the connection to potential security risks.
  - **Example:** `--plaintext`


## Starting server
After installing you should have a new binary called `wsnet-wssserver`.  
By default the server generates its own certificate and private key because Firefox doesn't allow mixed content on localhost, but it is allowed in Chrome. This behaviour can be disabled by using the `--plaintext` switch.  
By default this server generates a random path which is used to protect the server agains potential malicious JS from other pages trying to use the server. This can be disabled by `--disable-security`, but this also disables the `Origin` header check which is part of the same protection mechanism.  

If you wish to run it on localhost without any security (it's your life) use the following: `wsnet-wssserver --plaintext --disable-security`

# Roadmap

- [ ] **UDP Client and Server**: Add support for UDP client and server functionalities to handle datagram-based communication.
- [ ] **Authentication Proxy**: Introduce an authentication proxy feature to handle user authentication for network services.


# Contributing
Contributions are welcome! Please submit a pull request or open an issue if you have suggestions or find a bug.
