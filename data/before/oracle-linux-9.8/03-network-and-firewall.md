<!-- data/before/oracle-linux-9.8/03-network-and-firewall.md -->
# Oracle Linux 9.8 네트워크와 방화벽

## 1. 원칙

Oracle Linux 9에서는 NetworkManager를 네트워크 구성의 정본으로 사용한다. 제거된 legacy network scripts에 의존하지 않으며 영구 연결 프로파일은 keyfile 형식으로 관리한다. 호스트 방화벽은 `firewalld`를 기본 활성화하고 서비스 또는 포트 허용 범위를 최소화한다.

## 2. 테스트 네트워크

| 항목 | 예시 값 |
| --- | --- |
| 연결 이름 | `app-net` |
| 인터페이스 | `ens192` |
| IPv4 | `192.0.2.10/24` |
| 게이트웨이 | `192.0.2.1` |
| DNS | `192.0.2.53` |
| DNS 검색 도메인 | `example.internal` |
| firewalld zone | `work` |

예시 주소는 실제 환경에 적용하지 않는다. 실제 IP, VLAN, DNS, route는 승인된 네트워크 설계에서 가져온다.

## 3. 읽기 점검

```bash
nmcli general status
nmcli device status
nmcli connection show
ip -brief address
ip route show
nmcli device show ens192
firewall-cmd --state
firewall-cmd --get-active-zones
firewall-cmd --list-all --zone=work
```

## 4. 정적 IPv4 프로파일 예시

원격 서버의 네트워크 변경은 out-of-band console을 확보하고 유지보수 창에서 수행한다.

```bash
sudo nmcli connection add type ethernet ifname ens192 con-name app-net ipv4.method manual ipv4.addresses 192.0.2.10/24 ipv4.gateway 192.0.2.1 ipv4.dns 192.0.2.53 ipv4.dns-search example.internal ipv6.method disabled
sudo nmcli connection modify app-net connection.autoconnect yes
sudo nmcli connection up app-net
```

영구 사용자 프로파일의 기본 위치는 `/etc/NetworkManager/system-connections/`이다. 파일을 직접 편집할 때 권한과 구문 오류로 연결이 끊길 수 있으므로 자동화는 `nmcli`를 우선한다.

## 5. 방화벽 기준

Oracle Linux 9에서 `firewalld`는 기본 활성 서비스다. 상태를 우선 확인하고, runtime 변경을 검증한 뒤 permanent 설정으로 승격한다.

```bash
sudo systemctl enable --now firewalld
sudo firewall-cmd --zone=work --change-interface=ens192
sudo firewall-cmd --zone=work --add-service=ssh
sudo firewall-cmd --zone=work --add-port=8443/tcp
sudo firewall-cmd --zone=work --list-all
sudo firewall-cmd --runtime-to-permanent
sudo firewall-cmd --check-config
```

SSH와 애플리케이션 포트는 출발지 제한이 필요한지 별도 검토한다. 직접 포트보다 정의된 firewalld service를 우선하고, 불필요한 cockpit·HTTP·개발 포트는 열지 않는다.

## 6. 변경 검증

1. 새 연결이 `activated` 상태다.
2. default route와 DNS가 승인값이다.
3. 관리 접속이 유지된다.
4. `firewall-cmd --list-all`에 승인되지 않은 서비스와 포트가 없다.
5. 재부팅 후 연결과 방화벽 규칙이 유지된다.
6. 실제 주소와 호스트명이 외부 검색 질의 또는 일반 로그에 포함되지 않는다.

## 7. 롤백

새 연결 활성화 실패 시 console에서 이전 연결을 다시 올린다. permanent 방화벽 반영 전에는 runtime 규칙을 제거하거나 firewalld를 reload해 복구한다. 방화벽 서비스를 전체 비활성화하는 방식은 정상 롤백으로 사용하지 않는다.

## 8. 공식 근거

- [Network Configuration Tools](https://docs.oracle.com/en/operating-systems/oracle-linux/9/network/network-NetworkConfigurationTools.html)
- [Creating a keyfile Connection Profile Manually](https://docs.oracle.com/en/operating-systems/oracle-linux/9/network/network-CreateKeyfileConnectionProfile-manual.html)
- [Controlling the firewalld Service](https://docs.oracle.com/en/operating-systems/oracle-linux/9/firewall/firewall-ControllingtheFirewallService.html)
- [Configuring firewalld Zones](https://docs.oracle.com/en/operating-systems/oracle-linux/9/firewall/firewall-ConfiguringfirewalldZones.html)
