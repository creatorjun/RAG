<!-- data/before/oracle-linux-9.8/06-service-operations-runbook.md -->
# Oracle Linux 9.8 애플리케이션 서비스 운영 Runbook

## 1. 서비스 정의

이 문서는 `example-api.service`라는 가상 내부 API의 운영 절차를 설명한다. 서비스는 비특권 계정으로 실행되고 `/opt/example-api`의 읽기 전용 배포물과 `/srv/app-data/example-api`의 쓰기 데이터를 사용하며 `8443/tcp`에서 수신한다.

| 항목 | 값 |
| --- | --- |
| systemd unit | `example-api.service` |
| 실행 계정 | `example-api` |
| 바이너리 | `/opt/example-api/current/bin/example-api` |
| 환경 파일 | `/etc/example-api/example-api.env` |
| 데이터 | `/srv/app-data/example-api` |
| 로그 | journald |
| health endpoint | `https://127.0.0.1:8443/health` |

환경 파일의 실제 비밀값을 문서, 일반 로그, RAG 입력에 포함하지 않는다. 문서에는 비밀 참조 이름만 기록한다.

## 2. 일상 상태 점검

```bash
systemctl is-enabled example-api.service
systemctl is-active example-api.service
systemctl status example-api.service --no-pager
journalctl -u example-api.service --since '-15 min' --no-pager
ss -lntp
curl --fail --silent --show-error --max-time 5 --resolve ol98-app01.example.internal:8443:127.0.0.1 https://ol98-app01.example.internal:8443/health
df -hT /opt/example-api /srv/app-data/example-api /var/log
getenforce
firewall-cmd --list-all --zone=work
```

정상 조건은 프로세스 active, health 성공, 오류율 기준 이내, 필요한 포트만 수신, 디스크 여유 기준 충족, SELinux enforcing이다.

## 3. 배포 전 점검

1. 변경 승인과 배포물 SHA-256을 확인한다.
2. 현재 활성 버전과 이전 롤백 버전을 기록한다.
3. 데이터 schema 호환성과 백업 복구 지점을 확인한다.
4. DNF 또는 커널 변경이 함께 있는지 분리한다.
5. health, 핵심 API, 로그 오류율의 기준값을 수집한다.
6. 방화벽과 SELinux 추가 변경이 없는지 확인한다.

## 4. 표준 재시작

```bash
sudo systemctl stop example-api.service
sudo systemctl start example-api.service
sudo systemctl is-active example-api.service
sudo journalctl -u example-api.service -n 100 --no-pager
```

무응답 프로세스에 즉시 강제 종료를 사용하지 않는다. systemd timeout, 프로세스 상태, open file, I/O wait를 확인하고 정상 종료 시간을 기다린 뒤 장애 절차로 전환한다.

## 5. 장애 분류

| 증상 | 우선 확인 | 금지되는 단축 |
| --- | --- | --- |
| 서비스 기동 실패 | unit 상태, journal, 설정 유효성, 파일 권한 | SELinux 전체 비활성 |
| 포트 미수신 | process, bind 주소, socket, 방화벽 | firewalld 전체 중지 |
| 응답 지연 | CPU, 메모리, I/O, downstream, GC | 무제한 재시작 루프 |
| 디스크 임계 | 큰 파일, journal, core, backup, inode | 근거 없는 재귀 삭제 |
| 패치 후 실패 | 실행 커널, 패키지 변경, ABI, 설정 diff | 무검증 package downgrade |
| 커널 panic | Kdump 상태와 vmcore | 사고 증거 삭제 |

## 6. 패치 후 smoke test

```bash
cat /etc/oracle-release
uname -r
systemctl --failed
systemctl is-active chronyd firewalld example-api.service
getenforce
update-crypto-policies --show
curl --fail --silent --show-error --max-time 5 --resolve ol98-app01.example.internal:8443:127.0.0.1 https://ol98-app01.example.internal:8443/health
```

이 점검은 [플랫폼 기준](01-platform-baseline.md)의 일부와 의도적으로 겹친다. RAG 중복 제거 시험에서는 두 문서를 삭제하거나 합치지 않고 반복 주장으로 군집화한 뒤 출처를 모두 유지해야 한다.

## 7. 롤백

1. 신규 요청 유입을 차단하거나 drain한다.
2. 실패 시각과 배포·패키지·커널 변경을 기록한다.
3. 데이터 schema가 이전 애플리케이션과 호환되는지 확인한다.
4. 이전 검증 배포물로 원자적 포인터를 전환한다.
5. 서비스를 기동하고 health와 핵심 기능을 검증한다.
6. 롤백 결과와 남은 데이터 변경을 기록한다.

커널 롤백이 필요하면 console 접근을 확보하고 GRUB에서 이전 검증 커널을 선택한다. 기본 커널 영구 변경은 별도 승인 후 수행한다.

## 8. 사고 증거

다음을 보존한다.

- UTC 사고 시간선
- 서비스 unit 상태와 제한된 journal 범위
- 실행 커널과 패키지 변경 목록
- health 결과와 오류 코드
- Kdump `vmcore`와 메타데이터
- 방화벽·SELinux 차단 이벤트
- 수행한 명령과 승인 ID

비밀, 개인 식별자, 전체 환경 파일, 실제 내부 주소는 일반 사고 문서와 외부 질의에서 제거한다.

## 9. 종료 기준

- 서비스 health와 업무 smoke test 통과
- `systemctl --failed`의 신규 실패 없음
- 디스크, 메모리, 오류율 정상 범위
- 방화벽·SELinux·암호화 정책 기준 유지
- 장애 원인과 임시 조치 구분
- 후속 영구 조치와 담당자 지정
