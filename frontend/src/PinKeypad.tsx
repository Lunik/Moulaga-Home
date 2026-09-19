import { Icon } from './ui'

const digits = ['1', '2', '3', '4', '5', '6', '7', '8', '9']

export function PinKeypad({
  value,
  onChange,
  disabled = false,
  maxLength = 12,
  label = 'Code PIN',
}: {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  maxLength?: number
  label?: string
}) {
  const appendDigit = (digit: string) => {
    if (!disabled && value.length < maxLength) onChange(`${value}${digit}`)
  }
  const removeDigit = () => {
    if (!disabled && value.length > 0) onChange(value.slice(0, -1))
  }

  return (
    <div className="pin-keypad" aria-label={label} role="group">
      <output
        className="pin-keypad-display"
        aria-label={`${value.length} chiffre${value.length === 1 ? '' : 's'} saisi${value.length === 1 ? '' : 's'}`}
      >
        <span className="pin-keypad-dots" aria-hidden="true">
          {Array.from({ length: Math.max(4, value.length) }, (_, index) => (
            <span className={index < value.length ? 'filled' : ''} key={index} />
          ))}
        </span>
        <small>{value.length}/{maxLength}</small>
      </output>
      <div className="pin-keypad-grid">
        {digits.map((digit) => (
          <button
            aria-label={`Chiffre ${digit}`}
            disabled={disabled || value.length >= maxLength}
            key={digit}
            onClick={() => appendDigit(digit)}
            type="button"
          >
            {digit}
          </button>
        ))}
        <button
          className="pin-keypad-clear"
          disabled={disabled || value.length === 0}
          onClick={() => onChange('')}
          type="button"
        >
          Effacer
        </button>
        <button
          aria-label="Chiffre 0"
          disabled={disabled || value.length >= maxLength}
          onClick={() => appendDigit('0')}
          type="button"
        >
          0
        </button>
        <button
          aria-label="Effacer le dernier chiffre"
          className="pin-keypad-backspace"
          disabled={disabled || value.length === 0}
          onClick={removeDigit}
          type="button"
        >
          <Icon name="back" />
        </button>
      </div>
    </div>
  )
}
