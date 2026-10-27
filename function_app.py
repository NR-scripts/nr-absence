import azure.functions as func
from function_agenda import bp as agenda_bp
from function_absence import bp as absence_bp
from function_kantine import bp as kantine_bp
from function_absencemonth import bp as absencemonth_bp
from function_absenceyear import bp as absenceyear_bp


app = func.FunctionApp()

app.register_functions(agenda_bp)
app.register_functions(absence_bp)
app.register_functions(kantine_bp)
app.register_functions(absencemonth_bp)
app.register_functions(absenceyear_bp)