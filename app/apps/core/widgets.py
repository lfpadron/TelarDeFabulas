from django.forms import ClearableFileInput


class PrivateFileInput(ClearableFileInput):
    template_name = "core/widgets/private_file_input.html"

    def is_initial(self, value):
        return bool(value and getattr(value, "name", False))
