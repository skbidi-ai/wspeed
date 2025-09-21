from flask import Flask, render_template, request, jsonify
import math

app = Flask(__name__)

# Pet weight formula - base weights at each age
BASE_WEIGHTS = {
    1: 1.00, 2: 1.09, 3: 1.18, 4: 1.27, 5: 1.36, 6: 1.45, 7: 1.55, 8: 1.64, 9: 1.73, 10: 1.82,
    11: 1.91, 12: 2.00, 13: 2.09, 14: 2.18, 15: 2.27, 16: 2.36, 17: 2.45, 18: 2.55, 19: 2.64, 20: 2.73,
    21: 2.82, 22: 2.91, 23: 3.00, 24: 3.09, 25: 3.18, 26: 3.27, 27: 3.36, 28: 3.45, 29: 3.55, 30: 3.64,
    31: 3.73, 32: 3.82, 33: 3.91, 34: 4.00, 35: 4.09, 36: 4.18, 37: 4.27, 38: 4.36, 39: 4.45, 40: 4.55,
    41: 4.64, 42: 4.73, 43: 4.82, 44: 4.91, 45: 5.00, 46: 5.09, 47: 5.18, 48: 5.27, 49: 5.36, 50: 5.45,
    51: 5.55, 52: 5.64, 53: 5.73, 54: 5.82, 55: 5.91, 56: 6.00, 57: 6.09, 58: 6.18, 59: 6.27, 60: 6.36,
    61: 6.45, 62: 6.55, 63: 6.64, 64: 6.73, 65: 6.82, 66: 6.91, 67: 7.00, 68: 7.09, 69: 7.18, 70: 7.27,
    71: 7.36, 72: 7.45, 73: 7.55, 74: 7.64, 75: 7.73, 76: 7.82, 77: 7.91, 78: 8.00, 79: 8.09, 80: 8.18,
    81: 8.27, 82: 8.36, 83: 8.45, 84: 8.55, 85: 8.64, 86: 8.73, 87: 8.82, 88: 8.91, 89: 9.00, 90: 9.09,
    91: 9.18, 92: 9.27, 93: 9.36, 94: 9.45, 95: 9.55, 96: 9.64, 97: 9.73, 98: 9.82, 99: 9.91, 100: 10.00
}

def calculate_weight_multiplier(current_age, current_weight):
    """Calculate the multiplier based on current age and weight"""
    if current_age not in BASE_WEIGHTS:
        return None
    
    base_weight_at_current_age = BASE_WEIGHTS[current_age]
    multiplier = current_weight / base_weight_at_current_age
    return multiplier

def predict_weights(current_age, current_weight):
    """Predict weights for all ages based on current data"""
    multiplier = calculate_weight_multiplier(current_age, current_weight)
    if multiplier is None:
        return None
    
    predictions = {}
    for age in range(1, 101):
        if age in BASE_WEIGHTS:
            predicted_weight = BASE_WEIGHTS[age] * multiplier
            predictions[age] = round(predicted_weight, 2)
    
    return predictions

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/calculate', methods=['POST'])
def calculate():
    try:
        data = request.get_json()
        current_age = int(data['age'])
        current_weight = float(data['weight'])
        
        if current_age < 1 or current_age > 100:
            return jsonify({'error': 'Age must be between 1 and 100'}), 400
        
        if current_weight <= 0:
            return jsonify({'error': 'Weight must be greater than 0'}), 400
        
        predictions = predict_weights(current_age, current_weight)
        
        if predictions is None:
            return jsonify({'error': 'Invalid age provided'}), 400
        
        return jsonify({
            'current_age': current_age,
            'current_weight': current_weight,
            'predictions': predictions
        })
    
    except (ValueError, KeyError) as e:
        return jsonify({'error': 'Invalid input data'}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=False)