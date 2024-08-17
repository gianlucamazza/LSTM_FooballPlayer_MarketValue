import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from torch.utils.data import DataLoader, TensorDataset
from sklearn.metrics import mean_squared_error, r2_score
from src.utils.logger import get_logger

logger = get_logger(__name__)


def check_data_types(X, y):
    """Ensure that all features and target variables are numeric."""
    logger.info("Checking data types in features and target.")
    for column in X.columns:
        if X[column].dtype == "object":
            logger.error(
                f"Non-numeric column found: {column} with dtype: {X[column].dtype}"
            )
            raise ValueError(
                f"Non-numeric column found: {column}. Ensure all features are numeric."
            )
    if y.dtype == "object":
        logger.error(f"Target variable has non-numeric dtype: {y.dtype}")
        raise ValueError(
            "Target variable has non-numeric dtype. Ensure the target is numeric."
        )
    logger.info("All columns are numeric.")


def check_for_nan_inf(X, y):
    """Check for NaN or infinite values in the dataset."""
    logger.info("Checking for NaN and infinite values in the data.")
    if X.isnull().values.any() or y.isnull().values.any():
        logger.error("NaN values found in input data.")
        raise ValueError("NaN values detected in the input data.")
    if not np.isfinite(X.values).all() or not np.isfinite(y.values).all():
        logger.error("Infinite values found in input data.")
        raise ValueError("Infinite values detected in the input data.")
    logger.info("No NaN or infinite values found.")


def evaluate_model(model, X_val, y_val, device=None):
    """Evaluate the model using the validation dataset."""
    logger.info("Starting model evaluation")

    # Move model to the correct device
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    # Convert data to PyTorch tensors and move to device
    X_val_tensor = torch.FloatTensor(X_val.values).to(device)
    y_val_tensor = torch.FloatTensor(y_val.values).to(device)

    # Ensure model is in evaluation mode
    model.eval()

    with torch.no_grad():
        predictions = model(X_val_tensor).view(-1)
        mse = mean_squared_error(y_val_tensor.cpu(), predictions.cpu())
        rmse = np.sqrt(mse)
        r2 = r2_score(y_val_tensor.cpu(), predictions.cpu())

    logger.info(f"Evaluation results - MSE: {mse:.4f}, RMSE: {rmse:.4f}, R²: {r2:.4f}")
    return mse, rmse, r2


def train_model(
    model,
    X_train,
    y_train,
    X_val,
    y_val,
    epochs=100,
    batch_size=32,
    learning_rate=0.001,
    patience=10,
    weight_decay=1e-5,
    device=None,
):
    """Train the model using the provided training data with early stopping and regularization."""
    logger.info("Starting model training")

    # Check data types and integrity
    check_data_types(X_train, y_train)
    check_for_nan_inf(X_train, y_train)

    # Determine the device (CPU/GPU)
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Using device: {device}")

    # Move model to the correct device
    model.to(device)

    # Convert data to PyTorch tensors and move to device
    X_train_tensor = torch.FloatTensor(X_train.values).to(device)
    y_train_tensor = torch.FloatTensor(y_train.values).to(device)

    # Reshape X_train_tensor for LSTM if needed
    if len(X_train_tensor.shape) == 2:
        X_train_tensor = X_train_tensor.unsqueeze(1)  # Adding sequence length dimension

    # Create DataLoader
    train_dataset = TensorDataset(X_train_tensor, y_train_tensor)
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)

    # Loss function and optimizer with L2 regularization (weight decay)
    criterion = nn.MSELoss()
    optimizer = optim.Adam(
        model.parameters(), lr=learning_rate, weight_decay=weight_decay
    )

    best_val_loss = float("inf")
    epochs_no_improve = 0
    early_stop = False

    # Training loop with early stopping
    for epoch in range(epochs):
        model.train()
        total_loss = 0
        for batch_X, batch_y in train_loader:
            optimizer.zero_grad()
            outputs = model(batch_X)
            outputs = outputs.view(-1)  # Flatten the output to match the target
            loss = criterion(outputs, batch_y)
            if torch.isnan(loss) or torch.isinf(loss):
                logger.error(f"NaN or Inf detected in loss at epoch {epoch}")
                raise ValueError(f"NaN or Inf detected in loss at epoch {epoch}")
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        avg_loss = total_loss / len(train_loader)

        # Evaluate on validation set
        val_mse, val_rmse, val_r2 = evaluate_model(model, X_val, y_val, device)

        # Early stopping logic
        if val_mse < best_val_loss:
            best_val_loss = val_mse
            epochs_no_improve = 0
            best_model_state = model.state_dict()
            logger.info(f"Validation loss improved to {val_mse:.4f}. Saving model...")
        else:
            epochs_no_improve += 1
            logger.info(
                f"No improvement in validation loss for {epochs_no_improve} epochs."
            )

        if epochs_no_improve >= patience:
            logger.info("Early stopping triggered.")
            early_stop = True
            break

        if epoch % 10 == 0 or epoch == epochs - 1 or early_stop:  # Log periodically
            logger.info(
                f"Epoch [{epoch + 1}/{epochs}], Loss: {avg_loss:.4f}, Val MSE: {val_mse:.4f}"
            )

    # Load the best model state before early stopping
    model.load_state_dict(best_model_state)
    logger.info("Training completed successfully with early stopping.")
    return model.state_dict()
