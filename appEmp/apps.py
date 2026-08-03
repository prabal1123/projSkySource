from django.apps import AppConfig


class AppempConfig(AppConfig):
    name = 'appEmp'

    def ready(self):
        import appEmp.signals