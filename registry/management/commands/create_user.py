from getpass import getpass
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

class Command(BaseCommand):
    help='내부 관리자 또는 조회 계정을 생성합니다. 비밀번호는 화면에 표시하지 않습니다.'
    def add_arguments(self,parser):
        parser.add_argument('username')
        parser.add_argument('--manager',action='store_true')
    def handle(self,*args,**opts):
        User=get_user_model()
        if User.objects.filter(username=opts['username']).exists():
            raise CommandError('이미 존재하는 계정입니다.')
        password=getpass('비밀번호: ')
        if password!=getpass('비밀번호 확인: '):
            raise CommandError('비밀번호가 일치하지 않습니다.')
        user=User(username=opts['username'],is_staff=opts['manager'])
        try:
            validate_password(password,user)
        except ValidationError as exc:
            raise CommandError('; '.join(exc.messages))
        user.set_password(password); user.save()
        self.stdout.write(self.style.SUCCESS('계정을 생성했습니다.'))
