from flask_wtf import FlaskForm
from wtforms import SelectField, SubmitField
from wtforms.validators import DataRequired

class RecommendationForm(FlaskForm):
    budget = SelectField('Budget', 
                        choices=[('Low', 'Low'), 
                                ('Medium', 'Medium'), 
                                ('High', 'High')],
                        validators=[DataRequired()])
    
    category = SelectField('Category', 
                          choices=[('Cultural Landmark', 'Cultural Landmark'),
                                  ('Eco-tourism Spot', 'Eco-tourism Spot'),
                                  ('Religious Site', 'Religious Site'),
                                  ('Historical Site', 'Historical Site'),
                                  ('Local Experience', 'Local Experience'),
                                  ('Family Activity', 'Family Activity'),
                                  ('Cultural Experience', 'Cultural Experience')],
                          validators=[DataRequired()])